"""검토 관점 평가용 고정 설계 (#40, docs/07 「검토 관점 평가」).

평가 세트 문장마다 고정한 설계를 관점 하나에 넣어 단독으로 검토하고, 심은 결함을 맞췄는지 센다.
생성 파이프라인(A01~A04) 결과와 관계없이 관점만 잰다.
실제 리뷰 노드처럼 팩의 few-shot 예시를 넣는다.

- 고정 설계 파일은 평가 자료라 공개 저장소에 두지 않는다 (ADR-0014).
  저장소에는 이 도구와 합성 예시만 둔다.
- 결함을 맞춘 기준은 지적 대상(targets)에 기대 대상 ID가 있는지다. 지적 kind는 LLM이 정하는 글자라
  채점하지 않고 보고서에만 남긴다.
- 호출이 실패한 사례는 지적 0건으로 세지 않고 실패로 따로 센다. 지표 계산에서는 뺀다.

실행: uv run python -m specton.review.eval_fixtures <고정설계.yaml> [--out 결과.json]
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import ConfigDict, Field, ValidationError, model_validator

from specton.config import Settings
from specton.contracts import (
    Attribute,
    Cardinality,
    Contract,
    DesignState,
    Entity,
    Finding,
    Function,
    NfrCategory,
    Relationship,
    Requirement,
    RequirementType,
)
from specton.contracts.base import EntityId, NonEmptyText, ObjectId, ReqId
from specton.contracts.state import VersionInfo
from specton.llm.client import LLMClient
from specton.llm.errors import LLMError
from specton.llm.openai_transport import openai_client
from specton.llm.types import CallRecord
from specton.review.eval_normalization import prepare_normalized, state_provenance
from specton.review.perspective import (
    PERSPECTIVES_DIR,
    Perspective,
    PerspectiveError,
    load_perspective,
)
from specton.review.reviewer import review_perspective

CaseKind = Literal["normal", "alt_normal", "defect"]
DefectKind = Literal[
    "cardinality",
    "direction",
    "optional",
    "identifying",
    "multi_value",
    "repeating_group",
    "duplicate_fact",
    "transitive_dependency",
    "partial_dependency",
    "derived_value",
]
NORMAL_KINDS: frozenset[str] = frozenset({"normal", "alt_normal"})
# normalized는 파일에서 받지 않고 승인된 팩의 실제 정리 코드로 만든다.
SUPPORTED_INPUTS: frozenset[str] = frozenset(
    {"requirements", "functions", "entities", "relationships", "normalized"}
)
# 파일에 rationale이 없을 때 넣는 관계 근거. 판단을 흐리지 않게 근거 요구사항 ID만 적는다.
DEFAULT_RATIONALE = "요구사항 {}에 따른 관계"


class FixtureError(ValueError):
    """고정 설계 파일이나 관점이 평가에 맞지 않는다. LLM을 부르기 전에 멈춘다."""


class FixtureRequirement(Contract):
    id: ReqId
    text: NonEmptyText
    type: RequirementType
    nfr_category: NfrCategory | None = None


class FixtureFunction(Contract):
    id: ObjectId
    name: NonEmptyText
    description: NonEmptyText | None = None
    req_ids: tuple[ReqId, ...] = Field(min_length=1)


class FixtureEntity(Contract):
    id: EntityId
    name: NonEmptyText
    description: NonEmptyText | None = None
    attributes: tuple[Attribute, ...] | None = Field(default=None, min_length=1)
    req_ids: tuple[ReqId, ...] = ()


class FixtureRelationship(Contract):
    id: ObjectId
    parent: EntityId
    child: EntityId
    cardinality: Cardinality
    optional: bool
    identifying: bool = False
    req_ids: tuple[ReqId, ...] = Field(min_length=1)
    rationale: NonEmptyText | None = None


class ExpectedFinding(Contract):
    target: ObjectId  # 결함을 심은 설계 요소 ID
    defect: DefectKind  # 심은 결함 종류. 보고서용이며 채점 기준은 target이다


class FixtureCase(Contract):
    """원문 문장 하나에 대한 고정 설계 한 벌."""

    case_id: NonEmptyText
    source_id: NonEmptyText  # 근거 원문 ID (평가 세트 입력)
    case: CaseKind
    requirements: tuple[FixtureRequirement, ...] = Field(min_length=1)
    functions: tuple[FixtureFunction, ...] = ()
    entities: tuple[FixtureEntity, ...] = ()
    relationships: tuple[FixtureRelationship, ...] = ()
    expected: tuple[ExpectedFinding, ...] = ()

    @model_validator(mode="after")
    def _check_case(self) -> Self:
        if self.case == "defect" and not self.expected:
            raise ValueError(f"{self.case_id}: defect 사례에는 expected가 하나 이상 필요합니다")
        if self.case != "defect" and self.expected:
            raise ValueError(f"{self.case_id}: {self.case} 사례에는 expected를 두지 않습니다")
        ids = [e.id for e in self.entities] + [r.id for r in self.relationships]
        ids += [f.id for f in self.functions]
        ids += [a.id for e in self.entities for a in e.attributes or ()]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.case_id}: 설계 대상 ID가 중복됩니다")
        expected = [e.target for e in self.expected]
        if len(expected) != len(set(expected)):
            raise ValueError(f"{self.case_id}: 기대 대상 ID가 중복됩니다")
        unknown = _unknown_refs(self)
        if unknown:
            raise ValueError(
                f"{self.case_id}: 사례 안에 없는 ID를 가리킵니다: {', '.join(unknown)}"
            )
        return self


class FixtureSet(Contract):
    """고정 설계 파일 하나. 관점 하나에 대한 사례 묶음이다."""

    model_config = ConfigDict(populate_by_name=True)

    reviewer_id: NonEmptyText
    set_name: NonEmptyText = Field(alias="set")  # 평가 세트 이름·버전
    pack: NonEmptyText
    cases: tuple[FixtureCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique_cases(self) -> Self:
        ids = [c.case_id for c in self.cases]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise ValueError(f"case_id가 겹칩니다: {', '.join(duplicated)}")
        return self


def _unknown_refs(case: FixtureCase) -> list[str]:
    """관계·기능·기대 지적이 가리키는 ID 중 사례 안에 없는 것."""
    reqs = {r.id for r in case.requirements}
    entities = {e.id for e in case.entities}
    relationships = {r.id for r in case.relationships}
    targets = entities | relationships | {a.id for e in case.entities for a in e.attributes or ()}
    referenced = [
        *(i for e in case.entities for i in e.req_ids if i not in reqs),
        *(i for e in case.entities for a in e.attributes or () for i in a.req_ids if i not in reqs),
        *(i for f in case.functions for i in f.req_ids if i not in reqs),
        *(i for r in case.relationships for i in (r.parent, r.child) if i not in entities),
        *(i for r in case.relationships for i in r.req_ids if i not in reqs),
        *(e.target for e in case.expected if e.target not in targets),
    ]
    return sorted(set(referenced))


def load_fixture_set(path: Path) -> FixtureSet:
    """고정 설계 파일을 읽는다. 형식 오류는 파일 경로를 붙여 FixtureError로 알린다."""
    try:
        return FixtureSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise FixtureError(f"{path}: 고정 설계 파일을 읽지 못했습니다\n{exc}") from exc


def case_state(fixtures: FixtureSet, case: FixtureCase) -> DesignState:
    """사례 하나를 리뷰어가 받는 설계 상태로 바꾼다. 파일 값은 그대로 두고 필수 칸만 채운다."""
    return DesignState(
        run_id=f"eval-{case.case_id}",
        versions=VersionInfo(pack_id=fixtures.pack),
        requirements=tuple(
            _requirement(r, case.source_id, row) for row, r in enumerate(case.requirements, 1)
        ),
        functions=tuple(_function(f) for f in case.functions),
        entities=tuple(_entity(e, fixtures.pack, case) for e in case.entities),
        relationships=tuple(_relationship(r) for r in case.relationships),
    )


def _requirement(req: FixtureRequirement, source_id: str, row: int) -> Requirement:
    return Requirement(
        id=req.id,
        source_id=source_id,
        source_ref={"file_format": "csv", "row": row},
        text=req.text,
        draft_text=req.text,
        type=req.type,
        nfr_category=req.nfr_category,
        analysis_version=1,
    )


def _function(function: FixtureFunction) -> Function:
    return Function(
        id=function.id,
        name=function.name,
        description=function.description or function.name,
        req_ids=function.req_ids,
    )


def _entity(entity: FixtureEntity, pack: str, case: FixtureCase) -> Entity:
    """엔티티는 이름만 받으므로 키 속성 하나(`<이름>번호`)를 채운다.

    A05는 속성을 보지 않아 생략 시에만 보충한다. A08은 명시된 속성을 그대로 사용한다.
    """
    related = sorted(
        {i for r in case.relationships if entity.id in (r.parent, r.child) for i in r.req_ids}
    )
    req_ids = entity.req_ids or tuple(related) or (case.requirements[0].id,)
    key = {
        "id": f"{entity.id}-KEY",
        "name": f"{entity.name}번호",
        "data_type": "varchar",
        "length": 20,
        "is_key": True,
        "nullable": False,
        "req_ids": req_ids,
    }
    return Entity(
        id=entity.id,
        pack=pack,
        name=entity.name,
        description=entity.description or entity.name,
        attributes=entity.attributes if entity.attributes is not None else (key,),
        req_ids=req_ids,
    )


def _relationship(rel: FixtureRelationship) -> Relationship:
    return Relationship(
        id=rel.id,
        parent=rel.parent,
        child=rel.child,
        cardinality=rel.cardinality,
        optional=rel.optional,
        identifying=rel.identifying,
        rationale=rel.rationale or DEFAULT_RATIONALE.format(", ".join(rel.req_ids)),
        req_ids=rel.req_ids,
    )


@dataclass(frozen=True)
class CaseResult:
    """사례 하나의 검토 결과."""

    case: FixtureCase
    ok: bool
    error_code: str | None
    findings: tuple[Finding, ...]
    calls: tuple[CallRecord, ...]
    provenance: dict[str, str] = field(default_factory=dict)

    @property
    def expected_targets(self) -> tuple[str, ...]:
        return tuple(e.target for e in self.case.expected)

    @property
    def found(self) -> tuple[str, ...]:
        hit = {(t.kind, t.id) for f in self.findings for t in f.targets}
        kinds = _target_kinds(self.case)
        return tuple(t for t in self.expected_targets if (kinds[t], t) in hit)

    @property
    def missed(self) -> tuple[str, ...]:
        return tuple(t for t in self.expected_targets if t not in self.found)

    def matches(self, finding: Finding) -> bool:
        """기대 결함 대상을 가리킨 지적인지."""
        kinds = _target_kinds(self.case)
        expected = {(kinds[t], t) for t in self.expected_targets}
        return any((t.kind, t.id) in expected for t in finding.targets)


def _target_kinds(case: FixtureCase) -> dict[str, str]:
    return {
        **{e.id: "entity" for e in case.entities},
        **{a.id: "attribute" for e in case.entities for a in e.attributes or ()},
        **{r.id: "relationship" for r in case.relationships},
    }


def run_cases(
    client: LLMClient, perspective: Perspective, fixtures: FixtureSet, settings: Settings
) -> tuple[CaseResult, ...]:
    """사례마다 관점 하나만 검토한다. 관점이 평가에 맞지 않으면 호출 전에 멈춘다."""
    _check_perspective(perspective, fixtures)
    states = []
    for case in fixtures.cases:
        state = case_state(fixtures, case)
        if "normalized" in perspective.inputs:
            if not case.entities or any(e.attributes is None for e in case.entities):
                raise FixtureError(
                    f"{case.case_id}: normalized 평가에는 명시적 attributes가 필요합니다"
                )
            try:
                state = prepare_normalized(state, root=settings.pack_root)
            except ValueError as exc:
                raise FixtureError(f"{case.case_id}: 평가 자료 정리 오류: {exc}") from exc
        states.append(state)
    results = []
    remaining = settings.max_tokens_per_run
    for case, state in zip(fixtures.cases, states, strict=True):
        result = _run_case(client, perspective, fixtures, case, settings, state, remaining)
        remaining -= sum(c.input_tokens + c.output_tokens for c in result.calls)
        results.append(result)
    return tuple(results)


def _check_perspective(perspective: Perspective, fixtures: FixtureSet) -> None:
    if perspective.reviewer_id != fixtures.reviewer_id:
        raise FixtureError(
            f"고정 설계는 {fixtures.reviewer_id}용인데 관점은 {perspective.reviewer_id}입니다"
        )
    unsupported = sorted(set(perspective.inputs) - SUPPORTED_INPUTS)
    if unsupported:
        raise FixtureError(
            f"{perspective.reviewer_id}: 고정 설계로 아직 만들 수 없는 입력입니다: "
            f"{', '.join(unsupported)} (정리 결과는 정리 코드를 거쳐야 합니다)"
        )


def _run_case(
    client: LLMClient,
    perspective: Perspective,
    fixtures: FixtureSet,
    case: FixtureCase,
    settings: Settings,
    state: DesignState,
    token_budget: int,
) -> CaseResult:
    if token_budget <= 0:
        return CaseResult(case, False, "BUDGET_EXCEEDED", (), (), state_provenance(state))
    run = review_perspective(
        client, perspective, state, settings, pack=fixtures.pack, token_budget=token_budget
    )
    [branch] = run.results
    return CaseResult(
        case=case,
        ok=branch.ok,
        error_code=branch.error_code,
        findings=branch.findings,
        calls=run.calls,
        provenance=state_provenance(state),
    )


@dataclass(frozen=True)
class Summary:
    """결함 탐지 지표 (docs/07). 실패한 사례는 cases·failed_cases·토큰에만 센다."""

    cases: int
    failed_cases: int
    expected_total: int
    expected_found: int
    findings_total: int
    findings_matched: int
    normal_false_positives: int
    input_tokens: int
    output_tokens: int
    call_duration_ms: int
    retries: int

    @property
    def recall(self) -> float | None:
        """발견율: 맞춘 기대 결함 / 기대 결함."""
        return self.expected_found / self.expected_total if self.expected_total else None

    @property
    def precision(self) -> float | None:
        """지적 정확도: 기대 결함을 가리킨 지적 / 전체 지적."""
        return self.findings_matched / self.findings_total if self.findings_total else None


def summarize(results: Sequence[CaseResult]) -> Summary:
    done = [r for r in results if r.ok]
    calls = [c for r in results for c in r.calls]
    return Summary(
        cases=len(results),
        failed_cases=len(results) - len(done),
        expected_total=sum(len(r.expected_targets) for r in done),
        expected_found=sum(len(r.found) for r in done),
        findings_total=sum(len(r.findings) for r in done),
        findings_matched=sum(1 for r in done for f in r.findings if r.matches(f)),
        normal_false_positives=sum(len(r.findings) for r in done if r.case.case in NORMAL_KINDS),
        input_tokens=sum(c.input_tokens for c in calls),
        output_tokens=sum(c.output_tokens for c in calls),
        call_duration_ms=sum(c.duration_ms for c in calls),
        retries=sum(c.attempt > 1 for c in calls),
    )


def build_report(
    fixtures: FixtureSet, perspective: Perspective, results: Sequence[CaseResult]
) -> dict[str, Any]:
    """사례별 결과와 지표. 평가 자료가 담기므로 결과 파일도 비공개 위치에 둔다."""
    summary = summarize(results)
    return {
        "reviewer_id": fixtures.reviewer_id,
        "set": fixtures.set_name,
        "fixture_content_hash": hashlib.sha256(
            json.dumps(fixtures.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest(),
        "pack": fixtures.pack,
        "prompt_version": perspective.prompt_version,
        "models": sorted({c.model for r in results for c in r.calls}),
        "summary": {**asdict(summary), "recall": summary.recall, "precision": summary.precision},
        "cases": [_case_report(r) for r in results],
    }


def _case_report(result: CaseResult) -> dict[str, Any]:
    return {
        "case_id": result.case.case_id,
        "source_id": result.case.source_id,
        "case": result.case.case,
        "ok": result.ok,
        "error_code": result.error_code,
        "provenance": result.provenance,
        "calls": [call.model_dump(mode="json") for call in result.calls],
        "expected": [e.model_dump(mode="json") for e in result.case.expected],
        "found": list(result.found),
        "missed": list(result.missed),
        "findings": [
            {
                "kind": f.kind,
                "severity": f.severity.value,
                "targets": [t.model_dump(mode="json") for t in f.targets],
                "target_stage": f.target_stage.value if f.target_stage else None,
                "suggestion": f.suggestion,
            }
            for f in result.findings
        ],
    }


def summary_line(fixtures: FixtureSet, summary: Summary) -> str:
    return (
        f"{fixtures.reviewer_id} {fixtures.set_name}: 사례 {summary.cases}"
        f"(실패 {summary.failed_cases}) · 발견율 {summary.expected_found}/{summary.expected_total}"
        f" · 지적 정확도 {summary.findings_matched}/{summary.findings_total}"
        f" · 정상 오탐 {summary.normal_false_positives}"
    )


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m specton.review.eval_fixtures",
        description="고정 설계로 검토 관점 하나를 평가한다 (#40). 실제 LLM을 호출한다.",
    )
    parser.add_argument("fixtures", type=Path, help="고정 설계 YAML (비공개 평가 자료)")
    parser.add_argument("--out", type=Path, help="사례별 결과 JSON을 쓸 경로")
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        fixtures = load_fixture_set(args.fixtures)
        perspective = load_perspective(PERSPECTIVES_DIR / f"{fixtures.reviewer_id}.yaml")
        results = run_cases(openai_client(settings), perspective, fixtures, settings)
    except (FixtureError, PerspectiveError, OSError, LLMError) as exc:
        print(f"평가를 실행하지 못했습니다: {exc}", file=sys.stderr)
        return 2
    report = build_report(fixtures, perspective, results)
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_line(fixtures, summarize(results)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
