"""#17: 실행 설정의 팩에서 예시·용어를 읽고, 누락을 기본 팩으로 숨기지 않는다."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from specton.config import Settings
from specton.contracts import DesignState, Entity, Function, NormalizedModel, Requirement
from specton.contracts.requirements import SourceRequirement
from specton.llm.client import LLMClient
from specton.llm.stub import reply, stub_client
from specton.nodes import (
    a01_requirements,
    a02_functions,
    a03_entities,
    a04_relationships,
    a09_rework_router,
)
from specton.nodes.common import unwrap_data
from specton.packs.build import DEFAULT_ROOT
from specton.packs.examples import ExampleError
from specton.packs.loader import PackError
from specton.review.perspective import load_perspectives
from specton.review.reviewer import (
    CombinedReviewOutput,
    PerspectiveFindings,
    ReviewOutput,
    review_perspective,
    run_review,
)

AGENTS = tuple(f"A{i:02}" for i in range(1, 10))
PERSPECTIVES = load_perspectives()
OUTPUTS = {
    "A01": a01_requirements.A01Output.model_validate({"requirements": [{
        "source_block_ids": ["B-1"], "text": "창고를 등록한다", "type": "FR",
    }]}),
    "A02": a02_functions.A02Output.model_validate({"functions": [{
        "name": "창고 등록", "description": "창고를 등록한다", "req_ids": ["REQ-01"],
    }]}),
    "A03": a03_entities.A03Output.model_validate({"entities": [{
        "name": "창고", "description": "창고 정보", "req_ids": ["REQ-01"],
        "attributes": [{"name": "창고코드", "data_type": "varchar", "length": 10,
                        "is_key": True, "nullable": False, "req_ids": ["REQ-01"]}],
    }], "entity_ops": [{"function_id": "FUNC-01", "entity_name": "창고", "operations": ["C"]}]}),
    "A04": a04_relationships.A04Output(relationships=()),
    **{f"A{i:02}": ReviewOutput(findings=()) for i in range(5, 9)},
    "A09": a09_rework_router.A09Output(decision="data_model", rationale="설계 확인"),
}  # fmt: skip


def _marker(agent: str) -> str:
    return f"설정한 경로의 {agent} 전용 예시"


@pytest.fixture
def pack_root(tmp_path: Path) -> Path:
    root = tmp_path / "custom-packs"
    for pack in ("common", "inventory"):
        shutil.copytree(DEFAULT_ROOT / pack, root / pack)
    for agent in AGENTS:
        path = root / "inventory" / "examples" / f"{agent}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["examples"] = [
            {
                "source_id": f"configured-{agent}",
                "input": _marker(agent),
                "output": OUTPUTS[agent].model_dump(mode="json"),
            }
        ]
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return root


@pytest.fixture
def state() -> DesignState:
    return DesignState(
        run_id="run-1",
        source_requirements=(SourceRequirement(
            document_id="doc-1", block_id="B-1", source_ref={"file_format": "csv", "row": 2},
            source_text="창고를 등록한다", extraction_status="pass",
        ),),
        requirements=(Requirement(
            id="REQ-01", source_ref={"file_format": "csv", "row": 2},
            text="창고를 등록한다", draft_text="창고를 등록한다", type="FR", analysis_version=1,
        ),),
        functions=(Function(id="FUNC-01", name="창고 등록", description="창고를 등록한다",
                            req_ids=["REQ-01"]),),
        entities=(Entity.model_validate({
            **OUTPUTS["A03"].model_dump()["entities"][0],
            "id": "ENT-01", "pack": "inventory", "attributes": [{
                **OUTPUTS["A03"].model_dump()["entities"][0]["attributes"][0], "id": "ATTR-01",
            }],
        }),),
        normalized=NormalizedModel(
            pack="inventory", pack_version="fixture", rules_version="fixture",
            lexicon_digest="fixture", tables=(), foreign_keys=(),
        ),
    )  # fmt: skip


def _run(agent: str, client: LLMClient, state: DesignState, settings: Settings) -> None:
    if agent in ("A01", "A02", "A03", "A04"):
        module = {
            "A01": a01_requirements,
            "A02": a02_functions,
            "A03": a03_entities,
            "A04": a04_relationships,
        }[agent]
        module.run(client, state, settings, pack="inventory")
    elif agent == "A09":
        a09_rework_router.run(client, state, settings, pack="inventory", findings=())
    else:
        perspective = next(p for p in PERSPECTIVES if p.reviewer_id == agent)
        review_perspective(client, perspective, state, settings, pack="inventory")


@pytest.mark.parametrize("agent", AGENTS)
@pytest.mark.parametrize("relative", [False, True])
def test_each_agent_uses_configured_examples_in_its_prompt(
    agent: str, relative: bool, pack_root: Path, state: DesignState, monkeypatch: pytest.MonkeyPatch
) -> None:
    if relative:
        monkeypatch.chdir(pack_root.parent)
    root = Path(pack_root.name) if relative else pack_root
    client, transport = stub_client(reply(OUTPUTS[agent]))

    _run(agent, client, state, Settings(_env_file=None, pack_root=root))

    (request,) = transport.sent
    assert [m.role for m in request.messages] == ["system", "user", "assistant", "user"]
    assert unwrap_data(request.messages[1].content) == _marker(agent)


@pytest.mark.parametrize("agent", AGENTS)
@pytest.mark.parametrize("missing", ["pack", "example"])
def test_missing_configured_pack_or_example_stops_before_the_llm(
    agent: str, missing: str, pack_root: Path, state: DesignState
) -> None:
    if missing == "pack":
        shutil.rmtree(pack_root / "inventory")
    else:
        (pack_root / "inventory" / "examples" / f"{agent}.yaml").unlink()
    client, transport = stub_client(reply(OUTPUTS[agent]))

    with pytest.raises((ExampleError, PackError)):
        _run(agent, client, state, Settings(_env_file=None, pack_root=pack_root))
    assert not transport.sent


def test_a03_uses_terms_and_exemption_reasons_from_the_configured_pack(
    pack_root: Path, state: DesignState
) -> None:
    # 테스트 복사본의 용어를 하나로 줄여 기본 팩의 용어가 섞이지 않는지 확인한다.
    path = pack_root / "inventory" / "terms.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["terms"] = [t for t in data["terms"] if t["term"] == "창고코드"]
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    path = pack_root / "common" / "rules.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["crud_exemption_reasons"]["configured_reason"] = ["D"]
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    client, transport = stub_client(reply(OUTPUTS["A03"]))

    _run("A03", client, state, Settings(_env_file=None, pack_root=pack_root))

    data = json.loads(unwrap_data(transport.sent[0].messages[-1].content))["pack"]
    assert [term["term"] for term in data["terms"]] == ["창고코드"]
    assert data["terms"][0]["data_type"] == "varchar"
    assert data["terms"][0]["length"] == 10
    assert data["crud_exemption_reasons"]["configured_reason"] == ["D"]


def test_missing_configured_common_pack_stops_a03_before_the_llm(
    pack_root: Path, state: DesignState
) -> None:
    (pack_root / "common" / "domains.yaml").unlink()
    client, transport = stub_client(reply(OUTPUTS["A03"]))

    with pytest.raises(PackError):
        _run("A03", client, state, Settings(_env_file=None, pack_root=pack_root))
    assert not transport.sent


def _combined_output() -> CombinedReviewOutput:
    return CombinedReviewOutput(
        perspectives=tuple(
            PerspectiveFindings(reviewer_id=p.reviewer_id, findings=()) for p in PERSPECTIVES
        )
    )


def test_combined_review_uses_all_configured_examples(pack_root: Path, state: DesignState) -> None:
    client, transport = stub_client(reply(_combined_output()))
    settings = Settings(_env_file=None, pack_root=pack_root, review_mode="combined")

    result = run_review(client, PERSPECTIVES, state, settings, pack="inventory")

    assert result.complete
    for perspective in PERSPECTIVES:
        assert _marker(perspective.reviewer_id) in transport.sent[0].messages[0].content


@pytest.mark.parametrize("agent", ("A05", "A06", "A07", "A08"))
def test_combined_review_does_not_replace_a_missing_example_with_the_default(
    agent: str, pack_root: Path, state: DesignState
) -> None:
    (pack_root / "inventory" / "examples" / f"{agent}.yaml").unlink()
    client, transport = stub_client(reply(_combined_output()))
    settings = Settings(_env_file=None, pack_root=pack_root, review_mode="combined")

    with pytest.raises(ExampleError):
        run_review(client, PERSPECTIVES, state, settings, pack="inventory")
    assert not transport.sent


@pytest.mark.parametrize("mode", ("parallel", "combined"))
def test_review_without_a_pack_keeps_working_with_an_empty_pack_root(
    mode: str, tmp_path: Path, state: DesignState
) -> None:
    responses = [_combined_output()] if mode == "combined" else [ReviewOutput(findings=())] * 4
    client, _ = stub_client(*(reply(output) for output in responses))

    result = run_review(
        client,
        PERSPECTIVES,
        state,
        Settings(_env_file=None, pack_root=tmp_path, review_mode=mode),
        pack=None,
    )

    assert result.complete
