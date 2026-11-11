"""평가 전용 조건의 실제 API·DB·SQL·승인·다운로드 경계. 어휘·승인은 합성이다."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from specton.api.main import create_app
from specton.config import Settings
from specton.contracts import Attribute, BranchResult, DesignState, Entity, Function, Requirement
from specton.contracts.state import VersionInfo
from specton.evaluation.lexicon_overlay import compose_overlay
from specton.evaluation.pipeline import condition_subject, create_evaluation_graph, load_condition
from specton.graph import Node
from specton.ingest.tabular import read_csv
from specton.packs.build import DEFAULT_ROOT
from specton.packs.provenance import policy_digest
from specton.persistence.db import Pool, create_checkpointer
from specton.runner import Runner

pytestmark = pytest.mark.db
CSV = "요구사항 ID,요구사항명,상세 내용\nSFR-01,등록,품목을 등록한다.\n".encode()
WORD = "쩨큐시험어"


def write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def condition_file(tmp_path: Path) -> Path:
    source = tmp_path / "source.csv"
    source.write_text(f"word,english,abbr\n{WORD},Synthetic,ZZQ\n")
    spec = {
        "schema_version": 1,
        "scope": "evaluation_exploration",
        "condition_id": "synthetic-overlay",
        "dictionary_version": "synthetic-1",
        "pack": "inventory",
        "base_pack_version": "0.1.23",
        "base_common_version": "0.1.7",
        "base_policy_digest": policy_digest(DEFAULT_ROOT, "inventory"),
        "sources": {
            "synthetic": {
                "path": "source.csv",
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "hash_mode": "raw_bytes",
                "edition": "synthetic",
                "publisher": "synthetic",
                "url": "https://example.com/test",
                "license": "이용허락범위 제한 없음",
                "retrieved_on": "2026-11-11",
                "encoding": "utf-8-sig",
                "word_column": "word",
                "english_column": "english",
                "abbreviation_column": "abbr",
            }
        },
        "additions": [
            {
                "word": {
                    "word": WORD,
                    "english": "Synthetic",
                    "abbreviation": "ZZQ",
                    "definition": "합성 단위 시험 전용",
                    "is_classifier": False,
                    "domain_group": None,
                    "synonyms": [],
                    "forbidden_synonyms": [],
                },
                "source": "synthetic",
                "row": 2,
                "selection_reason": "합성 시험",
                "definition_basis": "합성 시험",
            }
        ],
    }
    write(tmp_path / "spec.json", spec)
    draft = compose_overlay(DEFAULT_ROOT, tmp_path / "spec.json", tmp_path / "draft")
    write(
        tmp_path / "reviews.json",
        {
            "subject_sha256": draft.subject_sha256,
            "reviews": [
                {
                    "role": role,
                    "reviewer": f"synthetic-{role}",
                    "decision": "approved",
                    "reference": "unit-test-only",
                }
                for role in ("R1", "R4")
            ],
        },
    )
    overlay = compose_overlay(
        DEFAULT_ROOT,
        tmp_path / "spec.json",
        tmp_path / "overlay",
        reviews=tmp_path / "reviews.json",
    )
    inp = tmp_path / "input.csv"
    inp.write_bytes(CSV)
    blocks = read_csv(inp, "old-document").requirements
    req = Requirement(
        id="REQ-01",
        draft_text="품목을 등록한다.",
        analysis_version=1,
        text="품목을 등록한다.",
        type="FR",
        source_ref=blocks[0].source_ref,
        source_text=blocks[0].source_text,
    )
    ent = Entity(
        id="ENT-01",
        name=WORD,
        pack="inventory",
        description="합성 품목",
        req_ids=["REQ-01"],
        attributes=[
            Attribute(
                id="ATTR-01",
                name="품목코드",
                data_type="varchar",
                length=10,
                is_key=True,
                nullable=False,
                req_ids=["REQ-01"],
            )
        ],
    )
    fn = Function(
        id="FUNC-01",
        name="등록",
        description="등록",
        req_ids=["REQ-01"],
        entity_ops=[{"entity_id": "ENT-01", "operations": ["C", "R", "U", "D"]}],
    )
    model = DesignState(
        run_id="seed",
        source_requirements=blocks,
        requirements=[req],
        functions=[fn],
        entities=[ent],
        versions=VersionInfo(pack_id="inventory", pack_version="0.1.23"),
    )
    write(tmp_path / "model.json", model.model_dump(mode="json"))
    raw = {
        "schema_version": 1,
        "scope": "post_observation_exploration",
        "condition_id": "synthetic-replay",
        "mode": "approved_model_replay",
        "overlay": str(overlay.folder),
        "overlay_subject_sha256": overlay.subject_sha256,
        "inputs": [
            {
                "case_id": "doc-1",
                "path": str(inp),
                "sha256": hashlib.sha256(CSV).hexdigest(),
                "approved_model": str(tmp_path / "model.json"),
                "approved_model_sha256": hashlib.sha256(
                    (tmp_path / "model.json").read_bytes()
                ).hexdigest(),
            }
        ],
    }
    raw["approval"] = {
        "role": "R1",
        "reviewer": "synthetic-R1",
        "decision": "approved",
        "subject_sha256": condition_subject(raw),
        "reference": "unit-test-only",
    }
    write(tmp_path / "condition.json", raw)
    return tmp_path / "condition.json"


def agents() -> dict[str, Node]:
    def reviewer(name: str) -> Node:
        return lambda state: {
            "branches": {
                name: BranchResult(branch=name, revision=state["design"].revision, ok=True)
            }
        }

    return {name: reviewer(name) for name in ("A05", "A06", "A07", "A08")}


def test_approved_model_uses_real_sql_approval_and_same_byte_download(
    pool: Pool, tmp_path: Path, condition_file: Path
) -> None:
    condition = load_condition(condition_file)
    settings = Settings(
        _env_file=None, storage_dir=tmp_path / "storage", pack_root=condition.overlay.base_root
    )
    graph = create_evaluation_graph(
        settings, create_checkpointer(pool), condition, agent_nodes=agents()
    )
    runner = Runner(pool, graph, settings)
    with TestClient(create_app(settings, pool)) as api:
        response = api.post(
            "/runs", files={"file": ("input.csv", CSV, "text/csv")}, data={"pack": "inventory"}
        )
        assert response.status_code == 202, response.text
        run = response.json()["run_id"]
        runner.run_pending()
        status = api.get(f"/runs/{run}").json()
        assert status["status"] == "awaiting_review", status
        view = api.get(f"/runs/{run}/view", params={"section": "design"}).json()
        assert view["normalization"]["tables"] == 1
        ddl = next(a for a in view["artifacts"] if a["kind"] == "ddl")
        assert ddl["validation"]["status"] == "passed"
        answer = api.post(
            f"/runs/{run}/resume",
            json={
                "interrupt_id": status["interrupt"]["interrupt_id"],
                "expected_revision": status["revision"],
                "response": {"kind": "review", "decision": "approve", "feedback": ""},
            },
        )
        assert answer.status_code == 202, answer.text
        runner.run_pending()
        status = api.get(f"/runs/{run}").json()
        assert status["status"] == "completed", status
        got = api.get(
            f"/runs/{run}/artifacts/ddl",
            params={"file_format": "sql", "revision": status["revision"]},
        )
        assert got.status_code == 200
        assert hashlib.sha256(got.content).hexdigest() == ddl["hash"]
        snapshot = graph.get_state({"configurable": {"thread_id": run}})
        assert snapshot.values["evaluation_condition"] == condition.subject
        assert (
            snapshot.values["design"].versions.model_names == {}
        )  # 설계 LLM 실행으로 꾸미지 않는다


def test_other_input_fails_before_a_design_node(
    pool: Pool, tmp_path: Path, condition_file: Path
) -> None:
    condition = load_condition(condition_file)
    settings = Settings(
        _env_file=None, storage_dir=tmp_path / "storage", pack_root=condition.overlay.base_root
    )
    graph = create_evaluation_graph(
        settings, create_checkpointer(pool), condition, agent_nodes=agents()
    )
    runner = Runner(pool, graph, settings)
    with TestClient(create_app(settings, pool)) as api:
        response = api.post(
            "/runs",
            files={"file": ("other.csv", CSV + b"\n", "text/csv")},
            data={"pack": "inventory"},
        )
        run = response.json()["run_id"]
        runner.run_pending()
        assert api.get(f"/runs/{run}").json()["status"] == "failed"
        assert not graph.get_state({"configurable": {"thread_id": run}}).values.get(
            "evaluation_condition"
        )


def test_condition_and_model_tampering_are_rejected(condition_file: Path) -> None:
    condition = load_condition(condition_file)
    model = condition.resolve(condition.spec.inputs[0].approved_model or "")
    model.write_text(model.read_text() + " ")
    with pytest.raises(ValueError, match="승인 모델"):
        condition.assert_current()


def test_new_generation_cannot_include_a_frozen_model(condition_file: Path) -> None:
    raw = json.loads(condition_file.read_text())
    raw["mode"] = "fresh_generation"
    raw["approval"]["subject_sha256"] = condition_subject(
        {k: v for k, v in raw.items() if k != "approval"}
    )
    write(condition_file, raw)
    with pytest.raises(ValueError, match="고정 모델"):
        load_condition(condition_file)


def test_batch_driver_preserves_manifest_and_download_bytes(
    pool: Pool, tmp_path: Path, condition_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specton.evaluation import run_pipeline
    from specton.llm.stub import stub_client

    client, _ = stub_client()
    monkeypatch.setattr(run_pipeline, "metered_client", lambda *a, **kw: client)
    monkeypatch.setattr(
        run_pipeline,
        "create_evaluation_graph",
        lambda settings, saver, condition, **kw: create_evaluation_graph(
            settings, saver, condition, agent_nodes=agents()
        ),
    )
    settings = Settings(_env_file=None)
    output = tmp_path / "execution"
    report = run_pipeline.execute(condition_file, settings, output)
    assert report["completed"] == report["total"] == 1, report["results"]
    assert report["calls"] == 0 and not report["fresh_generation"]
    assert report["results"][0]["artifact_count"] == 6
    assert (output / "doc-1" / "events.sse").exists()
    with pytest.raises(ValueError, match="덮어쓸"):
        run_pipeline.execute(condition_file, settings, output)
