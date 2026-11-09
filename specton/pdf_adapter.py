"""#17 PDF 후보: 승인본용 바이트를 비공개로 준비하고 같은 해시로 승인·게시한다.

렌더러의 draft=False는 문서 표식만 정한다. 실제 승인 여부는 ArtifactRef와 승인 DB가
정하며, 후보 PDF는 approved=False라 다운로드 API에 노출되지 않는다.
ERD(#209)와 기능 명세서(#243)가 같은 후보 규칙·표지 정보를 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from specton.artifacts import GeneratedArtifact, write_artifact
from specton.config import Settings
from specton.contracts import DesignState
from specton.model_hash import model_hash

if TYPE_CHECKING:
    from specton.contracts.normalized import NormalizedModel
    from specton.export.pdf import CoverInfo
    from specton.packs.loader import Pack

type PdfKind = Literal["erd", "functions"]


class RenderedPdf(Protocol):
    @property
    def pdf(self) -> bytes: ...

    @property
    def warnings(self) -> tuple[str, ...]: ...

    @property
    def blocked_urls(self) -> tuple[str, ...]: ...


type PdfRenderer = Callable[[DesignState], RenderedPdf]


@dataclass(frozen=True)
class PdfCandidate:
    generated: GeneratedArtifact
    warnings: tuple[str, ...]


def create_pdf_candidate(
    design: DesignState, *, storage_dir: Path, render: PdfRenderer, kind: PdfKind = "erd"
) -> PdfCandidate:
    """기존 고정 모델의 PDF를 한 번 렌더링한다. DB 승인·게시와 재생성은 하지 않는다."""
    model = design.normalized
    if model is None:
        raise ValueError("PDF 생성: 정리 결과가 없습니다")
    if (design.versions.pack_id, design.versions.pack_version) != (model.pack, model.pack_version):
        raise ValueError("PDF 생성: 실행과 정리 결과의 팩·버전이 다릅니다")
    result = render(design)
    if result.blocked_urls:
        raise ValueError("PDF 생성 중 외부 리소스 접근이 차단됐습니다")
    if not isinstance(result.pdf, bytes) or not result.pdf.startswith(b"%PDF-"):
        raise ValueError("PDF 생성기가 PDF 바이트를 반환하지 않았습니다")
    generated = write_artifact(storage_dir, design, kind, "pdf", result.pdf, approved=False)
    return PdfCandidate(generated, tuple(result.warnings))


def _recorded_pack(design: DesignState, settings: Settings) -> tuple[Pack, NormalizedModel]:
    """실행에 기록된 팩과 정리 모델. 모델이 없거나 팩 버전이 바뀌었으면 엔진을 부르지 않는다."""
    from specton.packs.loader import load_pack

    model = design.normalized
    if model is None or design.versions.pack_id is None:
        raise ValueError("PDF 생성: 정리된 팩 모델이 없습니다")
    pack = load_pack(design.versions.pack_id, root=settings.pack_root)
    if pack.manifest.version != design.versions.pack_version:
        raise ValueError("PDF 생성: 기록된 팩 버전과 현재 팩 버전이 다릅니다")
    return pack, model


def _cover(design: DesignState, pack: Pack, *, title: str) -> CoverInfo:
    """표지·쪽 머리 표식에 쓰는 실행 정보 (#14 manifest와 같은 이름)."""
    from specton.export.pdf import CoverInfo

    return CoverInfo(
        run_id=design.run_id,
        revision=design.revision,
        model_hash=model_hash(design),
        pack=pack.manifest.name,
        pack_version=pack.manifest.version,
        title=title,
    )


def erd_pdf_renderer(settings: Settings) -> PdfRenderer:
    """#199 팩 영역과 #209 공용 엔진을 소비한다. native PDF import는 실제 호출 때만 한다."""
    from specton.codegen.erd_areas import pack_areas
    from specton.export.pdf import MermaidCli, render_erd_pdf

    mermaid = MermaidCli(
        command=settings.mermaid_cli_command,
        puppeteer_config=settings.mermaid_puppeteer_config,
    )

    def render(design: DesignState) -> RenderedPdf:
        pack, model = _recorded_pack(design, settings)
        return render_erd_pdf(
            model, design.relationships,
            pack_areas(pack.manifest.name, root=settings.pack_root),
            _cover(design, pack, title="ERD"), draft=False, mermaid=mermaid,
        )  # fmt: skip

    return render


def function_spec_pdf_renderer(settings: Settings) -> PdfRenderer:
    """#243 엔진으로 기능 명세서 PDF를 만든다. Mermaid는 쓰지 않는다.

    입력 Markdown은 같은 revision에 저장되는 `.md`(#213 `render_function_spec`)와 같은 글이다.
    """
    from specton.codegen.function_spec import render_function_spec
    from specton.export.pdf import render_function_spec_pdf

    def render(design: DesignState) -> RenderedPdf:
        pack, _ = _recorded_pack(design, settings)
        return render_function_spec_pdf(
            render_function_spec(design), _cover(design, pack, title="기능 명세서"), draft=False
        )

    return render
