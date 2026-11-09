"""R1 PDF 후보: 파일·모델·팩 문맥, 차단 결과, 엔진 호출 계약."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from specton.codegen.function_spec import render_function_spec
from specton.codegen.normalize_step import normalize_design
from specton.config import Settings
from specton.contracts import DesignState, Entity, Function, Normalized, Requirement, VersionInfo
from specton.model_hash import model_hash
from specton.packs.build import DEFAULT_ROOT, read_yaml
from specton.pdf_adapter import create_pdf_candidate, erd_pdf_renderer, function_spec_pdf_renderer


@dataclass(frozen=True)
class _Pdf:
    pdf: bytes = b"%PDF-1.7\nfixture\n%%EOF"
    warnings: tuple[str, ...] = ()
    blocked_urls: tuple[str, ...] = ()


@pytest.fixture
def design() -> DesignState:
    state = DesignState(
        run_id="00000000-0000-4000-8000-000000000017", revision=2,
        versions=VersionInfo(pack_id="inventory", pack_version=str(
            read_yaml(DEFAULT_ROOT / "inventory/manifest.yaml")["version"])),
        requirements=(Requirement(
            id="REQ-01", source_ref={"file_format":"csv", "row":2}, type="FR",
            text="창고를 등록한다", draft_text="창고를 등록한다", analysis_version=1,
        ),),
        entities=(Entity.model_validate({
            "id":"ENT-01", "pack":"inventory", "name":"창고", "description":"창고",
            "req_ids":["REQ-01"], "attributes":[{
                "id":"ATTR-01", "name":"창고코드", "data_type":"varchar", "length":10,
                "is_key":True, "nullable":False, "req_ids":["REQ-01"],
            }],
        }),),
    )  # fmt: skip
    result = normalize_design(state)
    assert isinstance(result, Normalized), result
    return state.evolve(normalized=result.model)


def test_candidate_is_private_and_keeps_the_rendered_bytes_and_model(
    design: DesignState,
    tmp_path: Path,
) -> None:
    seen = []
    result = _Pdf(warnings=("영역 상세 글자가 작습니다",))

    def render(state: DesignState) -> _Pdf:
        seen.append(state)
        return result

    candidate = create_pdf_candidate(design, storage_dir=tmp_path, render=render)
    item = candidate.generated
    assert seen == [design] and candidate.warnings == result.warnings
    assert (item["ref"].kind, item["ref"].file_format, item["ref"].approved) == (
        "erd",
        "pdf",
        False,
    )
    assert item["ref"].hash == hashlib.sha256(result.pdf).hexdigest()
    assert item["model_hash"] == model_hash(design)
    assert (tmp_path / item["storage_ref"]).read_bytes() == result.pdf


@pytest.mark.parametrize("bad", ["missing_model", "pack", "version"])
def test_invalid_context_is_rejected_before_rendering(
    design: DesignState,
    tmp_path: Path,
    bad: str,
) -> None:
    invalid = (
        design.evolve(normalized=None)
        if bad == "missing_model"
        else design.evolve(
            versions=design.versions.evolve(
                **{"pack_id" if bad == "pack" else "pack_version": "different"}
            )
        )
    )

    def render(state: DesignState) -> _Pdf:
        pytest.fail("잘못된 모델·팩으로 PDF 렌더러를 부르면 안 됩니다")

    with pytest.raises(ValueError):
        create_pdf_candidate(invalid, storage_dir=tmp_path, render=render)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "result",
    [
        _Pdf(pdf=b"not PDF"),
        _Pdf(pdf=b""),
        _Pdf(blocked_urls=("file:///private/resource",)),
    ],
)
def test_bad_pdf_or_blocked_resources_are_not_written(
    design: DesignState,
    tmp_path: Path,
    result: _Pdf,
) -> None:
    with pytest.raises(ValueError) as error:
        create_pdf_candidate(design, storage_dir=tmp_path, render=lambda state: result)
    assert "private/resource" not in str(error.value)
    assert list(tmp_path.iterdir()) == []


def test_engine_exception_is_not_replaced_with_a_fake_pdf(
    design: DesignState, tmp_path: Path
) -> None:
    def render(state: DesignState) -> _Pdf:
        raise OSError("fixture native engine failure")

    with pytest.raises(OSError):
        create_pdf_candidate(design, storage_dir=tmp_path, render=render)
    assert list(tmp_path.iterdir()) == []


def test_real_engine_bridge_uses_recorded_cover_and_final_style(
    design: DesignState,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from specton.export import pdf

    settings = Settings(
        _env_file=None,
        storage_dir=tmp_path,
        mermaid_cli_command=("controlled-mmdc",),
        mermaid_puppeteer_config=tmp_path / "puppeteer.json",
    )
    captured: dict[str, Any] = {}

    def render(model: Any, relationships: Any, areas: Any, cover: Any, **kwargs: Any) -> _Pdf:
        captured.update(
            model=model, relationships=relationships, areas=areas, cover=cover, **kwargs
        )
        return _Pdf()

    monkeypatch.setattr(pdf, "render_erd_pdf", render)
    result = erd_pdf_renderer(settings)(design)
    assert result.pdf.startswith(b"%PDF-")
    assert (
        captured["model"] == design.normalized and captured["relationships"] == design.relationships
    )
    assert captured["cover"].run_id == design.run_id
    assert captured["cover"].revision == design.revision
    assert captured["cover"].model_hash == model_hash(design)
    assert captured["cover"].pack_version == design.versions.pack_version
    assert captured["draft"] is False  # 문서 표식만 정한다. 공개 승인은 DB 기록이 제어한다
    assert captured["mermaid"].command == settings.mermaid_cli_command
    assert captured["mermaid"].puppeteer_config == settings.mermaid_puppeteer_config


def test_pack_version_change_is_rejected_before_engine_call(
    design: DesignState,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from specton.export import pdf

    assert design.normalized is not None
    stale = design.evolve(
        normalized=design.normalized.evolve(pack_version="stale"),
        versions=design.versions.evolve(pack_version="stale"),
    )

    def render(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("버전이 다른 팩으로 PDF를 만들면 안 됩니다")

    monkeypatch.setattr(pdf, "render_erd_pdf", render)
    with pytest.raises(ValueError, match="팩 버전"):
        erd_pdf_renderer(Settings(_env_file=None, storage_dir=tmp_path))(stale)


def test_custom_pack_root_is_used_without_default_fallback(
    design: DesignState,
    tmp_path: Path,
) -> None:
    from specton.packs.loader import PackError

    with pytest.raises(PackError):
        erd_pdf_renderer(Settings(_env_file=None, pack_root=tmp_path))(design)


# ── 기능 명세서 PDF (#13 엔진 #243, R1 연결 #17) ─────────────────────


def _with_function(design: DesignState) -> DesignState:
    function = Function(
        id="FUNC-01",
        name="창고 등록",
        description="창고를 등록한다",
        req_ids=("REQ-01",),
        entity_ops=({"entity_id": "ENT-01", "operations": ("C", "R")},),
    )
    return design.evolve(functions=(function,))


def test_function_spec_candidate_is_private_under_its_own_kind(
    design: DesignState, tmp_path: Path
) -> None:
    result = _Pdf()
    candidate = create_pdf_candidate(
        design, storage_dir=tmp_path, render=lambda state: result, kind="functions"
    )
    ref = candidate.generated["ref"]
    assert (ref.kind, ref.file_format, ref.approved) == ("functions", "pdf", False)
    assert ref.hash == hashlib.sha256(result.pdf).hexdigest()


def test_function_spec_bridge_renders_the_stored_markdown_with_the_recorded_cover(
    design: DesignState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PDF는 저장되는 `.md`와 같은 Markdown으로 만들고, 표지에 실행에 기록된 값을 쓴다."""
    from specton.export import pdf

    spec = _with_function(design)
    captured: dict[str, Any] = {}

    def render(markdown: str, cover: Any, **kwargs: Any) -> _Pdf:
        captured.update(markdown=markdown, cover=cover, **kwargs)
        return _Pdf()

    monkeypatch.setattr(pdf, "render_function_spec_pdf", render)
    result = function_spec_pdf_renderer(Settings(_env_file=None, storage_dir=tmp_path))(spec)
    assert result.pdf.startswith(b"%PDF-")
    assert captured["markdown"] == render_function_spec(spec)
    cover = captured["cover"]
    assert (cover.run_id, cover.revision, cover.model_hash) == (
        spec.run_id,
        spec.revision,
        model_hash(spec),
    )
    assert (cover.pack, cover.pack_version) == ("inventory", spec.versions.pack_version)
    assert cover.title == "기능 명세서"
    assert captured["draft"] is False  # 문서 표식만 정한다. 공개 승인은 DB 기록이 제어한다


def test_function_spec_pack_version_change_is_rejected_before_engine_call(
    design: DesignState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specton.export import pdf

    spec = _with_function(design)
    assert spec.normalized is not None
    stale = spec.evolve(
        normalized=spec.normalized.evolve(pack_version="stale"),
        versions=spec.versions.evolve(pack_version="stale"),
    )

    def render(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("버전이 다른 팩으로 PDF를 만들면 안 됩니다")

    monkeypatch.setattr(pdf, "render_function_spec_pdf", render)
    with pytest.raises(ValueError, match="팩 버전"):
        function_spec_pdf_renderer(Settings(_env_file=None, storage_dir=tmp_path))(stale)
