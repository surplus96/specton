"""#17 실행기: lease·노드마다 저장·HITL 재개·취소·실패·시작 시 대조 (ADR-0012)."""

import io
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.serde.event_hooks import SerdeEvent, register_serde_event_listener
from openpyxl import Workbook  # type: ignore[import-untyped]

from specton.config import Settings
from specton.contracts import (
    BranchResult,
    DesignState,
    Entity,
    Finding,
    Requirement,
    ResumeRequest,
    RunState,
    RunStatus,
    SseEventType,
)
from specton.contracts.base import TargetStage
from specton.contracts.requirements import QualityIssue
from specton.graph import GraphState, Node, build_graph, initial_state
from specton.llm.errors import LLMRefusalError
from specton.normalization_node import normalization_node
from specton.packs.build import DEFAULT_ROOT, read_yaml
from specton.parse_node import parse_node
from specton.persistence import lease
from specton.persistence.db import Pool, create_checkpointer
from specton.persistence.errors import BlockingFindingsError
from specton.persistence.runs import (
    add_document,
    answer_interrupt,
    create_run,
    events_after,
    get_run,
    request_cancel,
)
from specton.persistence.snapshots import get_view
from specton.runner import Runner

pytestmark = pytest.mark.db

OWNER = "owner-a"
REQUIREMENTS_OK = {"kind": "requirements", "answers": []}
APPROVE = {"kind": "review", "decision": "approve", "feedback": ""}


@pytest.fixture(autouse=True)
def only_registered_checkpoint_types() -> Iterator[None]:
    """체크포인트를 다시 읽을 때 목록 밖 타입을 막거나 경고하지 않는다 (#131).

    LangGraph 경고는 프로세스에서 한 번만 나오므로 로그 대신 serde 이벤트를 모은다.
    """
    events: list[SerdeEvent] = []
    unregister = register_serde_event_listener(events.append)
    yield
    unregister()
    assert [(e["kind"], e["module"], e["name"]) for e in events] == []


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        lease_seconds=5,
        lease_renew_seconds=1,
        runner_poll_seconds=0.05,
    )


class _World:
    """실행기와 그래프. 방문한 노드를 순서대로 남긴다. 새 인스턴스는 서버 재시작과 같다."""

    def __init__(
        self, pool: Pool, settings: Settings, nodes: Mapping[str, Node] | None = None
    ) -> None:
        self.pool = pool
        self.visited: list[str] = []
        recorded = {name: self._record(name, node) for name, node in (nodes or {}).items()}
        for name in ("parse", "a02", "a03"):
            recorded.setdefault(name, self._record(name, lambda state: {}))
        # 기본 A01은 확인할 것이 있는 요구사항을 낸다. 그래야 분석 확인(HITL 1)에서 멈춘다
        recorded.setdefault("a01", self._record("a01", _with_requirement))
        self.graph = build_graph(recorded, checkpointer=create_checkpointer(pool))
        self.runner = Runner(pool, self.graph, settings)

    def _record(self, name: str, node: Node) -> Node:
        def wrapped(state: GraphState) -> Mapping[str, Any]:
            self.visited.append(name)
            return node(state)

        return wrapped

    def create(self) -> UUID:
        with self.pool.connection() as conn:
            return create_run(conn, OWNER, "inventory").run_id

    def status(self, run_id: UUID) -> RunStatus:
        with self.pool.connection() as conn:
            return get_run(conn, run_id, OWNER)

    def answer(self, run_id: UUID, response: Mapping[str, Any]) -> None:
        current = self.status(run_id)
        assert current.interrupt is not None
        request = ResumeRequest.model_validate(
            {
                "interrupt_id": current.interrupt.interrupt_id,
                "expected_revision": current.revision,
                "response": dict(response),
            }
        )
        with self.pool.connection() as conn:
            answer_interrupt(conn, run_id, OWNER, request)

    def events(self, run_id: UUID) -> list[SseEventType]:
        with self.pool.connection() as conn:
            return [e.event for e in events_after(conn, run_id, OWNER, 0)]

    def status_stages(self, run_id: UUID) -> list[str | None]:
        with self.pool.connection() as conn:
            events = events_after(conn, run_id, OWNER, 0)
        return [e.data.stage for e in events if e.event is SseEventType.STATUS]

    def lease_is_live(self, run_id: UUID) -> bool:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM job_lease WHERE run_id = %s AND lease_until > now()", (run_id,)
            ).fetchone()
        return row is not None


@pytest.fixture
def world(pool: Pool, settings: Settings) -> Iterator[Callable[..., _World]]:
    worlds: list[_World] = []

    def make(nodes: Mapping[str, Node] | None = None) -> _World:
        w = _World(pool, settings, nodes)
        worlds.append(w)
        return w

    yield make
    for w in worlds:
        w.runner.stop()


def test_queued_run_stops_at_requirements_check_and_releases_lease(
    world: Callable[..., _World],
) -> None:
    w = world()
    run_id = w.create()

    w.runner.run_pending()

    status = w.status(run_id)
    assert status.status is RunState.AWAITING_REQUIREMENTS
    assert status.interrupt is not None and status.interrupt.kind == "requirements"
    assert not w.lease_is_live(run_id)
    assert w.events(run_id)[-1] is SseEventType.INTERRUPT


def test_a_new_run_starts_with_its_pack_in_the_design(world: Callable[..., _World]) -> None:
    seen: list[DesignState] = []

    def a01(state: GraphState) -> Mapping[str, Any]:
        seen.append(state["design"])
        return {}

    w = world({"a01": a01})
    with w.pool.connection() as conn:
        create_run(conn, OWNER, "maintenance", pack_version="0.1.4")

    w.runner.run_pending()

    [design] = seen
    assert design.versions.pack_id == "maintenance"
    assert design.versions.pack_version == "0.1.4"


CSV = "요구사항 ID,요구사항명,상세 내용\nSFR-001,입고 등록,입고를 등록한다\n,출고,출고한다\n"


def _upload(w: _World, storage: Path, content: str | bytes, file_format: str = "csv") -> UUID:
    """문서 하나를 올린 실행. 업로드 API처럼 `<run_id>/<document_id>.<형식>`에 둔다."""
    document_id = uuid4()
    with w.pool.connection() as conn:
        run_id = create_run(conn, OWNER, "inventory").run_id
        ref = f"{run_id}/{document_id}.{file_format}"
        (storage / str(run_id)).mkdir()
        data = content.encode("utf-8") if isinstance(content, str) else content
        (storage / ref).write_bytes(data)
        add_document(
            conn, run_id, document_id=document_id, file_name=f"a.{file_format}",
            file_format=file_format, file_hash="h", storage_ref=ref,
        )  # fmt: skip
    return run_id


def _decisions(w: _World, run_id: UUID) -> dict[str, tuple[str | None, str | None]]:
    with w.pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT block_id, user_decision, excluded_reason FROM source_block
            JOIN document USING (document_id) WHERE run_id = %s ORDER BY block_id
            """,
            (run_id,),
        ).fetchall()
    return {r["block_id"]: (r["user_decision"], r["excluded_reason"]) for r in rows}


def test_uploaded_document_is_read_and_stops_for_the_extraction_check(
    world: Callable[..., _World], tmp_path: Path
) -> None:
    w = world({"parse": parse_node(tmp_path)})
    run_id = _upload(w, tmp_path, CSV)

    w.runner.run_pending()

    status = w.status(run_id)
    assert status.status is RunState.AWAITING_INPUT
    assert status.interrupt is not None and status.interrupt.kind == "extraction"
    assert _decisions(w, run_id) == {"csv:2": (None, None), "csv:3": (None, None)}
    assert "a01" not in w.visited


def test_extraction_answer_is_saved_on_the_blocks_and_moves_to_analysis(
    world: Callable[..., _World], tmp_path: Path
) -> None:
    w = world({"parse": parse_node(tmp_path)})
    run_id = _upload(w, tmp_path, CSV + ",반품,반품한다\n")
    w.runner.run_pending()

    w.answer(
        run_id,
        {
            "kind": "extraction",
            "confirmed": True,
            "excluded_blocks": [{"block_id": "csv:4", "reason": "2차 범위"}],
        },
    )
    w.runner.run_pending()

    assert w.status(run_id).status is RunState.AWAITING_REQUIREMENTS
    assert _decisions(w, run_id) == {
        "csv:2": (None, None),
        "csv:3": ("confirmed", None),
        "csv:4": ("excluded", "2차 범위"),
    }


def test_unreadable_document_fails_the_run_as_extraction_failed(
    world: Callable[..., _World], tmp_path: Path
) -> None:
    w = world({"parse": parse_node(tmp_path)})
    run_id = _upload(w, tmp_path, "이름,값\n가,1\n")

    w.runner.run_pending()

    status = w.status(run_id)
    assert status.status is RunState.FAILED
    assert status.error is not None
    assert status.error.code == "EXTRACTION_FAILED"
    assert status.error.retryable is False


def test_skipped_sheets_are_recorded_for_the_extraction_screen(
    world: Callable[..., _World], tmp_path: Path
) -> None:
    """요구사항 표가 없는 시트는 안내 한 줄로 status 이벤트에 남는다 (docs/09 UI-02)."""
    book = Workbook()
    book.active.title = "표지"
    sheet = book.create_sheet("요구사항")
    sheet.append(["요구사항 ID", "요구사항명", "상세 내용"])
    sheet.append(["SFR-001", "입고 등록", "입고를 등록한다"])
    data = io.BytesIO()
    book.save(data)
    w = world({"parse": parse_node(tmp_path)})
    run_id = _upload(w, tmp_path, data.getvalue(), file_format="xlsx")

    w.runner.run_pending()

    with w.pool.connection() as conn:
        events = events_after(conn, run_id, OWNER, 0)
    [note] = [e for e in events if e.data.payload.get("info") == "skipped_sheets"]
    assert note.event is SseEventType.STATUS
    assert (note.data.stage, note.data.payload["sheets"]) == ("parsing", ["표지"])
    assert note.data.message == "요구사항을 읽지 않은 시트가 있습니다"
    assert w.status(run_id).status is RunState.AWAITING_REQUIREMENTS
    assert _decisions(w, run_id) == {"xlsx:요구사항:2": (None, None)}
    with w.pool.connection() as conn:
        [document] = conn.execute(
            "SELECT document_id FROM document WHERE run_id = %s", (run_id,)
        ).fetchall()
        replay = events_after(conn, run_id, OWNER, note.id - 1)
    assert note.data.payload["document_id"] == str(document["document_id"])
    assert replay[0] == note


def test_extraction_failure_shows_the_parser_notice_and_detail(
    world: Callable[..., _World], tmp_path: Path
) -> None:
    """파서 안내 두 문장 (#19): `message`는 짧은 안내(notice).

    SSE `error` payload의 `detail`은 「자세히 보기」 문장이다.
    """
    w = world({"parse": parse_node(tmp_path)})
    run_id = _upload(w, tmp_path, "이름,값\n가,1\n")  # 요구사항 표 머리글이 없다

    w.runner.run_pending()

    status = w.status(run_id)
    assert status.error is not None
    assert status.error.message == "요구사항 표를 찾지 못했어요. 표의 칸 이름을 확인해 주세요."
    with w.pool.connection() as conn:
        [error] = [e for e in events_after(conn, run_id, OWNER, 0) if e.event is SseEventType.ERROR]
    assert error.data.message == status.error.message
    assert error.data.payload["code"] == "EXTRACTION_FAILED"
    assert "위쪽 20행 안에" in error.data.payload["detail"]
    assert status.error.detail == error.data.payload["detail"]


def test_other_failures_keep_the_fixed_message_without_detail(
    world: Callable[..., _World],
) -> None:
    def refuse(state: GraphState) -> Mapping[str, Any]:
        raise LLMRefusalError("내부 프롬프트 내용")

    w = world({"a01": refuse})
    run_id = w.create()

    w.runner.run_pending()

    with w.pool.connection() as conn:
        [error] = [e for e in events_after(conn, run_id, OWNER, 0) if e.event is SseEventType.ERROR]
    assert error.data.message == "모델이 응답을 거절했습니다. 입력을 확인해 주세요."
    assert "detail" not in error.data.payload
    status = w.status(run_id)
    assert status.error is not None and status.error.detail is None


def test_excluding_a_related_requirement_is_recorded_as_a_run_event(
    world: Callable[..., _World], tmp_path: Path
) -> None:
    """ADR-0015 결정 5: 제외는 막지 않고, 경고를 status 이벤트로 남긴다."""
    w = world({"parse": parse_node(tmp_path)})
    rows = "요구사항 ID,요구사항명,상세 내용,관련 요구사항\n"
    # SFR-002는 상세 내용이 비어 review 블록이다 (pass 블록은 제외할 수 없다, #120)
    rows += "SFR-001,입고 등록,입고를 등록한다,SFR-002\nSFR-003,출고,출고한다,\nSFR-002,반품,,\n"
    run_id = _upload(w, tmp_path, rows)
    w.runner.run_pending()
    exclude = [{"block_id": "csv:4", "reason": "2차 범위"}]

    w.answer(run_id, {"kind": "extraction", "confirmed": True, "excluded_blocks": exclude})
    w.runner.run_pending()

    with w.pool.connection() as conn:
        events = events_after(conn, run_id, OWNER, 0)
    [warning] = [e for e in events if e.data.payload.get("warning") == "excluded_related"]
    assert warning.event is SseEventType.STATUS
    assert warning.data.payload["block_id"] == "csv:4"
    assert warning.data.payload["related_block_ids"] == ["csv:2"]


def test_answers_resume_the_run_to_completion(world: Callable[..., _World]) -> None:
    w = world()
    run_id = w.create()
    w.runner.run_pending()

    w.answer(run_id, REQUIREMENTS_OK)
    w.runner.run_pending()
    review = w.status(run_id)
    w.answer(run_id, APPROVE)
    w.runner.run_pending()

    assert review.status is RunState.AWAITING_REVIEW
    assert review.interrupt is not None and review.interrupt.kind == "review"
    done = w.status(run_id)
    assert done.status is RunState.COMPLETED
    assert done.interrupt is None
    assert w.visited.count("a01") == 1  # 재개는 멈춘 곳부터
    assert w.events(run_id)[-1] is SseEventType.COMPLETED


def test_revise_asks_again_and_completes_after_approval(world: Callable[..., _World]) -> None:
    """수정 요청을 A09가 판단하지 못하면 새 확인 요청으로 다시 최종 검토를 묻는다 (#114 R3 확인)."""
    w = world()  # A09는 stub: 복귀 단계를 정하지 못한다
    run_id = w.create()
    w.runner.run_pending()
    w.answer(run_id, REQUIREMENTS_OK)
    w.runner.run_pending()
    first = w.status(run_id).interrupt

    w.answer(run_id, {"kind": "review", "decision": "revise", "feedback": "보완"})
    w.runner.run_pending()
    again = w.status(run_id)
    w.answer(run_id, APPROVE)
    w.runner.run_pending()

    assert first is not None
    assert again.status is RunState.AWAITING_REVIEW
    assert again.interrupt is not None and again.interrupt.interrupt_id != first.interrupt_id
    assert w.status(run_id).status is RunState.COMPLETED


# 품질 경고가 있어 분석 확인(HITL 1)에서 멈추는 요구사항
REQ = Requirement(
    id="REQ-01",
    source_ref={"file_format": "csv", "row": 2},
    text="입고를 등록한다",
    draft_text="입고를 등록한다",
    type="FR",
    quality_issues=[QualityIssue(kind="ambiguous", message="입고 단위가 없습니다")],
    analysis_version=1,
)


def _with_requirement(state: GraphState) -> Mapping[str, Any]:
    return {"design": state["design"].evolve(requirements=(REQ,))}


def _critical_rule(state: GraphState) -> Mapping[str, Any]:
    """규칙 검사(#15) 자리. critical은 규칙 지적만 쓸 수 있다 (ADR-0010)."""
    finding = Finding.model_validate(
        {
            "id": f"RULE-01-{state['design'].iteration}-1",
            "source": "rule",
            "rule_code": "RULE-01",
            "kind": "missing_function",
            "severity": "critical",
            "targets": [{"kind": "requirement", "id": "REQ-01"}],
            "evidence": [{"req_id": "REQ-01", "quote": "입고"}],
            "suggestion": "기능을 추가한다",
            "target_stage": None,  # A09 stub이 판단하지 못해 HITL 2로 간다
            "fingerprint": "fp-critical",
            "iteration": state["design"].iteration,
        }
    )
    return {"rule_findings": (finding,)}


def test_skipped_requirements_check_is_announced_for_the_progress_screen(
    world: Callable[..., _World],
) -> None:
    """확인할 것이 없으면 HITL 1에서 멈추지 않고, UI-04가 「분석 확인 생략」을 보이도록 알린다."""
    clean = REQ.evolve(quality_issues=())
    w = world({"a01": lambda state: {"design": state["design"].evolve(requirements=(clean,))}})
    run_id = w.create()

    w.runner.run_pending()

    with w.pool.connection() as conn:
        events = events_after(conn, run_id, OWNER, 0)
    statuses = [(e.data.stage, e.data.message) for e in events if e.event is SseEventType.STATUS]
    stages = [stage for stage, _ in statuses]
    assert "awaiting_requirements" not in stages
    assert stages[stages.index("analysing") + 1] == "designing"
    assert ("designing", "확인할 항목이 없어 분석 확인을 생략했습니다") in statuses
    assert w.status(run_id).status is RunState.AWAITING_REVIEW


def test_requirements_are_saved_for_the_view_before_the_requirements_check(
    world: Callable[..., _World],
) -> None:
    """HITL 1에서 멈추기 전에 모델을 저장해 화면용 조회에 요구사항이 보인다 (#113)."""
    w = world({"a01": _with_requirement})
    run_id = w.create()

    w.runner.run_pending()

    with w.pool.connection() as conn:
        view = get_view(conn, run_id, OWNER, "requirements")
    assert w.status(run_id).status is RunState.AWAITING_REQUIREMENTS
    assert [item["id"] for item in view.items] == ["REQ-01"]


def test_requirements_answer_is_applied_to_the_saved_model(world: Callable[..., _World]) -> None:
    """HITL 1의 split 답이 설계 모델에 반영되고, 새 ID는 서버가 붙인다 (docs/06 resume)."""
    w = world({"a01": _with_requirement})
    run_id = w.create()
    w.runner.run_pending()
    split = {"req_id": "REQ-01", "action": "split", "texts": ["입고를 등록한다", "입고를 승인한다"]}

    w.answer(run_id, {"kind": "requirements", "answers": [split]})
    w.runner.run_pending()

    with w.pool.connection() as conn:
        view = get_view(conn, run_id, OWNER, "requirements")
    assert w.status(run_id).status is RunState.AWAITING_REVIEW
    assert [(item["id"], item["text"]) for item in view.items] == [
        ("REQ-01", "입고를 등록한다"),
        ("REQ-02", "입고를 승인한다"),
    ]


def test_findings_saved_before_final_review_block_approval(world: Callable[..., _World]) -> None:
    """HITL 2 전에 지적을 저장해야 approve가 차단 오류를 검사할 수 있다 (06 문서 resume)."""
    w = world({"a01": _with_requirement, "rules": _critical_rule})
    run_id = w.create()
    w.runner.run_pending()
    w.answer(run_id, REQUIREMENTS_OK)
    w.runner.run_pending()

    with w.pool.connection() as conn:
        view = get_view(conn, run_id, OWNER, "review")
    assert w.status(run_id).status is RunState.AWAITING_REVIEW
    assert [item["fingerprint"] for item in view.items] == ["fp-critical"]
    with pytest.raises(BlockingFindingsError):
        w.answer(run_id, APPROVE)


def test_normalization_manual_review_is_saved_and_blocks_approval_after_restart(
    world: Callable[..., _World],
) -> None:
    """생성·리뷰 없이 저장한 정리 지적도 승인 검사와 체크포인트 재개에 사용한다 (#17)."""

    def normalize(state: GraphState) -> Mapping[str, Any]:
        return {
            **_critical_rule(state),
            "normalization_failed": True,
            "requires_manual_review": True,
        }

    def forbidden(state: GraphState) -> Mapping[str, Any]:
        pytest.fail("정리 실패 뒤 생성·LLM 검토·A09·내보내기가 실행됐습니다")

    skipped = ("ddl", "erd", "rtm", "rules", "A05", "A06", "A07", "A08", "a09", "export")
    nodes = {name: forbidden for name in skipped} | {"normalize": normalize}
    w = world(nodes)
    run_id = w.create()
    w.runner.run_pending()
    w.answer(run_id, REQUIREMENTS_OK)
    w.runner.run_pending()

    before = w.status(run_id)
    assert before.status is RunState.AWAITING_REVIEW
    assert before.revision == 0
    assert not w.lease_is_live(run_id)
    assert not set(skipped).intersection(w.visited)
    assert "generating" not in w.status_stages(run_id)
    with w.pool.connection() as conn:
        view = get_view(conn, run_id, OWNER, "review")
        events = events_after(conn, run_id, OWNER, 0)
    assert [item["fingerprint"] for item in view.items] == ["fp-critical"]
    assert events[-1].data.payload["hitl_reason"] == "manual_review"
    assert events[-1].data.payload["failed_branches"] == []

    w.runner.stop()
    restarted = world(nodes)
    with pytest.raises(BlockingFindingsError):
        restarted.answer(run_id, APPROVE)
    assert restarted.status(run_id) == before
    restarted.answer(run_id, {"kind": "review", "decision": "hold", "feedback": "보류"})
    restarted.runner.run_pending()
    assert restarted.status(run_id).status is RunState.AWAITING_REVIEW
    assert restarted.visited == []


def test_approval_is_linked_to_the_saved_model_and_completes(
    world: Callable[..., _World],
) -> None:
    """승인은 그 revision의 저장된 모델에 연결되고, 승인 뒤 같은 모델 저장도 실패하지 않는다."""
    w = world({"a01": _with_requirement})
    run_id = w.create()
    w.runner.run_pending()
    w.answer(run_id, REQUIREMENTS_OK)
    w.runner.run_pending()

    w.answer(run_id, APPROVE)
    w.runner.run_pending()

    with w.pool.connection() as conn:
        row = conn.execute(
            "SELECT snapshot_id FROM approval WHERE run_id = %s AND decision = 'approve'",
            (run_id,),
        ).fetchone()
    assert row is not None and row["snapshot_id"] is not None
    assert w.status(run_id).status is RunState.COMPLETED


def test_actual_normalization_is_saved_and_rebuilt_after_rework(
    world: Callable[..., _World],
) -> None:
    """정리 노드가 반환한 모델은 실행기가 저장하며, 새 설계 전 비운다 (#17·#143)."""
    seen: list[bool] = []

    def a03(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        seen.append(design.normalized is None)
        entity = Entity.model_validate({
            "id": "ENT-eq", "pack": "maintenance", "name": "설비", "description": "설비",
            "req_ids": ["REQ-01"], "attributes": [{
                "id": "ATTR-eq", "name": "설비코드", "data_type": "varchar", "length": 10,
                "is_key": True, "nullable": False, "req_ids": ["REQ-01"],
            }],
        })  # fmt: skip
        return {"design": design.evolve(entities=(entity,))}

    def rules(state: GraphState) -> Mapping[str, Any]:
        return _critical_rule(state) if state["design"].revision == 0 else {"rule_findings": ()}

    def forbidden(*args: Any) -> Any:
        pytest.fail("정상 정리 결과가 실패 변환기로 전달됐습니다")

    nodes = {
        "a03": a03, "rules": rules,
        "normalize": normalization_node(forbidden, root=DEFAULT_ROOT),
        "a09": lambda state: {"router_stage": TargetStage.DATA_MODEL},
    }  # fmt: skip
    w = world(nodes)
    version = str(read_yaml(DEFAULT_ROOT / "maintenance/manifest.yaml")["version"])
    with w.pool.connection() as conn:
        run_id = create_run(conn, OWNER, "maintenance", pack_version=version).run_id
    w.runner.run_pending()
    w.answer(run_id, REQUIREMENTS_OK)
    w.runner.run_pending()
    assert w.status(run_id).status is RunState.AWAITING_REVIEW
    assert w.status(run_id).revision == 1
    assert seen == [True, True]
    with w.pool.connection() as conn:
        rows = conn.execute(
            "SELECT revision, normalized_model -> 'normalized' AS model "
            "FROM model_snapshot WHERE run_id = %s ORDER BY revision",
            (run_id,),
        ).fetchall()
    assert [r["revision"] for r in rows] == [0, 1]
    assert all(r["model"]["tables"][0]["physical_name"] == "eqpm" for r in rows)
    w.runner.stop()
    restarted = world(nodes)
    restarted.answer(run_id, APPROVE)
    restarted.runner.run_pending()
    assert restarted.status(run_id).status is RunState.COMPLETED
    assert seen == [True, True]  # 재시작 뒤 저장된 정리 결과를 사용하고 A03을 다시 부르지 않는다


def test_failed_review_branch_is_shown_in_the_final_review_event(
    world: Callable[..., _World],
) -> None:
    """리뷰 가지가 실패해도 run은 실패하지 않고, HITL 2 이벤트에 불완전 검토를 싣는다 (TC-F14)."""

    def refuse(state: GraphState) -> Mapping[str, Any]:
        failed = BranchResult(
            branch="A06", revision=state["design"].revision, ok=False, error_code="LLM_UNAVAILABLE"
        )
        return {"branches": {"A06": failed}}

    w = world({"A06": refuse})
    run_id = w.create()
    w.runner.run_pending()
    w.answer(run_id, REQUIREMENTS_OK)

    w.runner.run_pending()

    assert w.status(run_id).status is RunState.AWAITING_REVIEW
    with w.pool.connection() as conn:
        last = events_after(conn, run_id, OWNER, 0)[-1]
    assert last.event is SseEventType.INTERRUPT
    assert last.data.payload["failed_branches"] == ["A06"]


def test_status_events_follow_each_saved_state(world: Callable[..., _World]) -> None:
    w = world()
    run_id = w.create()

    w.runner.run_pending()

    assert w.status_stages(run_id) == ["parsing", "analysing", "awaiting_requirements"]


def test_cancel_requested_during_a_node_ends_at_the_node_boundary(
    world: Callable[..., _World],
) -> None:
    holder: list[_World] = []

    def cancel_now(state: GraphState) -> Mapping[str, Any]:
        w = holder[0]
        run_id = UUID(state["design"].run_id)
        with w.pool.connection() as conn:
            request_cancel(conn, run_id, OWNER, w.status(run_id).revision)
        return {}

    w = world({"a01": cancel_now})
    holder.append(w)
    run_id = w.create()

    w.runner.run_pending()

    assert w.status(run_id).status is RunState.CANCELLED
    assert "analysing" not in w.status_stages(run_id)  # 취소된 노드 결과는 저장하지 않는다
    assert w.events(run_id)[-1] is SseEventType.CANCELLED
    assert not w.lease_is_live(run_id)


def test_node_failure_marks_the_run_failed_without_internal_details(
    world: Callable[..., _World],
) -> None:
    def refuse(state: GraphState) -> Mapping[str, Any]:
        raise LLMRefusalError("내부 프롬프트 내용")

    w = world({"a01": refuse})
    run_id = w.create()

    w.runner.run_pending()

    status = w.status(run_id)
    assert status.status is RunState.FAILED
    assert status.error is not None
    assert status.error.code == "LLM_REFUSED"
    assert status.error.retryable is False
    assert "프롬프트" not in status.error.message
    assert w.events(run_id)[-1] is SseEventType.ERROR
    assert not w.lease_is_live(run_id)


def test_a_new_runner_resumes_from_the_last_checkpoint(world: Callable[..., _World]) -> None:
    """서버 재시작: 앞 실행기가 노드 경계에서 멈추면 새 실행기가 체크포인트부터 잇는다."""
    holder: list[_World] = []

    def stop_server(state: GraphState) -> Mapping[str, Any]:
        holder[0].runner.request_stop()
        return {}

    first = world({"parse": stop_server})
    holder.append(first)
    run_id = first.create()
    first.runner.run_pending()
    assert first.status(run_id).status is RunState.PARSING
    assert not first.lease_is_live(run_id)

    restarted = world()
    restarted.runner.run_pending()

    assert restarted.status(run_id).status is RunState.AWAITING_REQUIREMENTS
    assert "parse" not in restarted.visited


def test_startup_saves_a_checkpoint_that_is_ahead_of_the_app_state(
    world: Callable[..., _World],
) -> None:
    """체크포인트는 남았는데 앱 저장 전에 죽은 경우: 그 지점의 앱 저장을 다시 한다."""
    w = world()
    run_id = w.create()
    config = {"configurable": {"thread_id": str(run_id)}}
    w.graph.invoke(
        initial_state(DesignState(run_id=str(run_id))),
        config,  # type: ignore[arg-type]
        interrupt_after=["parse"],
    )
    assert w.status(run_id).status is RunState.QUEUED

    w.runner.run_pending()

    assert w.status_stages(run_id) == ["parsing", "analysing", "awaiting_requirements"]
    assert w.status(run_id).status is RunState.AWAITING_REQUIREMENTS


def test_startup_fails_a_run_whose_checkpoint_cannot_be_matched(
    world: Callable[..., _World],
) -> None:
    """앱 상태로 맞출 수 없는 체크포인트(queued → analysing)는 `failed`로 기록한다."""
    w = world()
    run_id = w.create()
    config = {"configurable": {"thread_id": str(run_id)}}
    w.graph.invoke(
        initial_state(DesignState(run_id=str(run_id))),
        config,  # type: ignore[arg-type]
        interrupt_after=["a01"],
    )

    w.runner.run_pending()

    status = w.status(run_id)
    assert status.status is RunState.FAILED
    assert status.error is not None and status.error.code == "INTERNAL"


def test_lost_lease_stops_the_run_without_saving(world: Callable[..., _World]) -> None:
    holder: list[_World] = []

    def steal_lease(state: GraphState) -> Mapping[str, Any]:
        run_id = UUID(state["design"].run_id)
        with holder[0].pool.connection() as conn:
            conn.execute("UPDATE job_lease SET lease_until = now() WHERE run_id = %s", (run_id,))
            assert lease.acquire(conn, run_id, "other-worker", 60)
        return {}

    w = world({"a01": steal_lease})
    holder.append(w)
    run_id = w.create()

    w.runner.run_pending()

    assert w.status(run_id).status is RunState.PARSING  # a01 결과는 저장하지 않는다
    assert "wait_requirements" not in w.visited
    assert w.lease_is_live(run_id)  # 다른 실행자의 lease는 건드리지 않는다


def test_background_runner_picks_up_new_and_answered_runs(world: Callable[..., _World]) -> None:
    w = world()
    w.runner.start()
    run_id = w.create()

    _wait_for(w, run_id, RunState.AWAITING_REQUIREMENTS)
    w.answer(run_id, REQUIREMENTS_OK)
    _wait_for(w, run_id, RunState.AWAITING_REVIEW)


def test_cancel_and_lease_at_the_same_moment_never_leave_a_cancelled_run_leased(
    pool: Pool,
) -> None:
    """취소(API)와 lease 잡기(실행기)가 동시에 일어나도 취소된 run을 잡지 않는다 (#108 리뷰)."""
    for _ in range(20):
        with pool.connection() as conn:
            run_id = create_run(conn, OWNER, "inventory").run_id
        barrier = threading.Barrier(2)
        acquired: list[bool] = []

        def cancel(run_id: UUID = run_id, barrier: threading.Barrier = barrier) -> None:
            with pool.connection() as conn:
                barrier.wait()
                request_cancel(conn, run_id, OWNER, 0)

        def take(
            run_id: UUID = run_id,
            barrier: threading.Barrier = barrier,
            acquired: list[bool] = acquired,
        ) -> None:
            with pool.connection() as conn:
                barrier.wait()
                acquired.append(lease.acquire(conn, run_id, "w1", 60))

        threads = [threading.Thread(target=cancel), threading.Thread(target=take)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with pool.connection() as conn:
            final = get_run(conn, run_id, OWNER).status
        if final is RunState.CANCELLED:
            assert acquired == [False]
        else:
            assert final is RunState.CANCEL_REQUESTED
            assert acquired == [True]


def _wait_for(w: _World, run_id: UUID, status: RunState, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if w.status(run_id).status is status:
            return
        time.sleep(0.05)
    raise AssertionError(f"{status}에 도달하지 못했습니다: {w.status(run_id).status}")
