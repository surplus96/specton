"""모델 정리 실패 → 규칙 지적 (#15). 정리 문제(`Problem`)를 검토 단계의 `Finding`으로 바꾼다.

처리 기준은 #15 댓글의 처리안과 #157·#15에서 R1이 정한 연결 방식을 따른다.

- 설계를 고쳐야 하는 문제는 복귀 단계(`target_stage`)가 있는 재작업 지적이 된다.
- 사전 보완·명명 규칙 결정처럼 같은 입력으로 다시 만들어도 풀리지 않는 문제는 복귀 단계를
  두지 않고 `requires_manual_review=True`로 알린다. 하나라도 있으면 사람 확인이 우선이다.
- 팩 불일치(`PACK_MISMATCH`)와 결과 검사 실패(`OUTPUT_TRACE`)는 실행 오류다. R1 어댑터가 먼저
  거르며, 이 변환기에 들어오면 지적으로 바꾸지 않고 멈춘다.

지적 대상은 원래 요구사항·기능·엔티티·속성·관계 ID여야 한다. 정리가 실패하면 완성된 테이블이
없으므로, 테이블·컬럼 ID는 입력 설계와 ID 계산(`specton.ids.stable_id`)으로 되짚는다.
되짚지 못하면 임의 대상으로 잇지 않고 멈춘다.

복귀 단계는 대상 종류·문제 세부 유형으로 계산한 뒤 팩의 handling 정책을 적용한다.
RULE-01·02·04·06의 dynamic은 계산한 경로를 보존하고, manual은 사람 조치를 우선한다.

이 모듈은 LLM client와 그래프·노드 모듈을 import하지 않는다.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypedDict, get_args

from specton.contracts import DesignState, Finding, Relationship
from specton.contracts.base import Cardinality, TargetStage
from specton.contracts.findings import FindingSource, FindingTarget, Severity
from specton.contracts.normalized import Problem, ProblemCode
from specton.contracts.state import ObjectKind, TraceIssueKind
from specton.ids import stable_id
from specton.packs.build import DEFAULT_ROOT
from specton.packs.loader import RulePolicy, load_common
from specton.review.fingerprint import fingerprint
from specton.review.rule_policy import apply_policy


class NormalizationFailureReview(TypedDict):
    """변환 결과. R1 정리 노드(`normalization_node.FailureReview`)와 같은 키를 쓴다."""

    findings: tuple[Finding, ...]
    requires_manual_review: bool


type FailureMapper = Callable[[DesignState, tuple[Problem, ...]], NormalizationFailureReview]


# 문제 코드 → (규칙 코드, 사람 확인 여부). #15 댓글 처리안. FK 충돌·입력 추적은 따로 정한다.
_RULES: dict[ProblemCode, tuple[str, bool]] = {
    ProblemCode.NO_PRIMARY_KEY: ("RULE-03", False),
    ProblemCode.DOMAIN_TYPE_MISMATCH: ("RULE-03", False),
    ProblemCode.PARENT_WITHOUT_KEY: ("RULE-04", False),
    ProblemCode.OPTIONAL_IDENTIFYING: ("RULE-04", False),
    ProblemCode.IDENTIFYING_CYCLE: ("RULE-04", False),
    ProblemCode.REQUIRED_SELF_REFERENCE: ("RULE-04", False),
    ProblemCode.UNRESOLVED_NAME: ("RULE-05", True),
    ProblemCode.NAMING_RULE_MISSING: ("RULE-05", True),
    ProblemCode.NAME_TOO_LONG: ("RULE-05", True),
    ProblemCode.RESERVED_WORD: ("RULE-05", True),
    ProblemCode.DUPLICATE_NAME: ("RULE-05", True),
}
# FK 컬럼 충돌: D13은 자식이 부모 키와 같은 이름의 속성을 이미 가진 설계 문제, D4는 다른 관계의
# FK와 물리명이 겹치는 명명 문제다 (#15 댓글, R1 #157 인계: decision 값으로 구분).
_FK_CONFLICT: dict[str, tuple[str, bool]] = {"D13": ("RULE-04", False), "D4": ("RULE-05", True)}
# 처리하지 않는 관계: D8은 A04 인계 규칙(#79) 위반이라 설계 재작업, D4는 지원(이름 규칙)이 없어
# 사람이 지원 방안을 정한다. 지원 부족을 LLM 재작업으로 풀게 하지 않는다 (#15 R1 댓글 2번).
_UNSUPPORTED: dict[str, tuple[str, bool]] = {"D8": ("RULE-04", False), "D4": ("RULE-04", True)}
_BY_DECISION: dict[ProblemCode, dict[str, tuple[str, bool]]] = {
    ProblemCode.FK_COLUMN_CONFLICT: _FK_CONFLICT,
    ProblemCode.UNSUPPORTED_RELATIONSHIP: _UNSUPPORTED,
}
_TRACE_KINDS: frozenset[str] = frozenset(get_args(TraceIssueKind))
_TRACE_SUGGESTIONS: dict[str, str] = {
    "missing_req_ids": "근거 요구사항(req_ids)을 채운다.",
    "unknown_req_id": "현재 요구사항에 있는 ID만 참조하게 고친다.",
    "unknown_entity_ref": "현재 설계에 있는 엔티티만 참조하게 고친다.",
    "duplicate_id": "겹치는 ID를 서로 다르게 만든다.",
}
_OBJECT_KINDS: frozenset[str] = frozenset(get_args(ObjectKind))
_STAGE_BY_KIND: dict[str, TargetStage] = {
    "requirement": TargetStage.REQUIREMENTS,
    "function": TargetStage.FUNCTIONS,
    "entity": TargetStage.DATA_MODEL,
    "attribute": TargetStage.DATA_MODEL,
    "relationship": TargetStage.DATA_MODEL,
}
_SUGGESTIONS: dict[str, str] = {
    "no_primary_key": "행을 구분하는 키 속성을 두거나, 부모 키를 물려받는 식별 관계로 바꾼다.",
    "domain_type_mismatch": "속성 타입·길이를 같은 이름 팩 용어의 도메인에 맞추거나 이름을 바꾼다.",
    "parent_without_key": "부모 엔티티에 키 속성을 먼저 둔다.",
    "optional_identifying_conflict": "식별 관계를 필수로 바꾸거나 비식별 관계로 바꾼다.",
    "identifying_cycle": "식별 관계의 순환을 끊는다.",
    "required_self_reference": "자기참조를 선택 관계로 바꿔 최상위 행이 들어갈 수 있게 한다.",
    "unsupported_relationship:D8": "자기참조·N:M 관계는 비식별 관계로 바꾼다 (A04 규칙).",
    "unsupported_relationship:D4": (
        "자기참조 N:M은 아직 지원하지 않는다. 관계의 업무 의미는 바꾸지 말고, "
        "연결 테이블 칸 이름 규칙 등 지원 방안을 정한다."
    ),
    "fk_column_conflict:D13": "자식의 부모 키 속성을 지우고 FK는 관계에서 파생되게 한다.",
    "fk_column_conflict:D4": "같은 부모를 여러 번 참조하는 FK의 이름 규칙을 정하거나 관계를 본다.",
    "unresolved_name": "팩 용어·사전에 없는 낱말을 팩에 등록하거나 사전 낱말로 된 이름을 쓴다.",
    "naming_rule_missing": "필요한 명명 규칙을 naming.yaml에 정한다.",
    "name_too_long": "더 짧은 이름을 쓰거나 명명 규칙을 다시 본다.",
    "reserved_word": "예약어와 겹치지 않는 이름을 쓴다.",
    "duplicate_name": "물리명이 겹치는 이름을 서로 다르게 짓는다.",
}


def rule_severities(*, root: Path = DEFAULT_ROOT) -> dict[str, Severity]:
    """공통 팩 `rules.yaml`의 규칙별 심각도. 정리 노드와 같은 팩 위치(`root`)를 넘긴다.

    심각도가 아직 null인 규칙은 빼며, 그 규칙의 지적이 필요해지면 변환기가 멈춘다.
    """
    rules = load_common(root=root).rules.rules
    return {r.id: Severity(r.severity) for r in rules if r.severity is not None}


def failure_mapper(
    severities: Mapping[str, Severity], *, policies: Mapping[str, RulePolicy] | None = None
) -> FailureMapper:
    """정리 노드에 넘길 변환 함수. 심각도처럼 팩에서 읽는 설정은 바깥에서 준비해 넣는다.

    예: `normalization_node(failure_mapper(rule_severities(root=root)), root=root)`
    """
    settings = dict(severities)

    def map_failure(
        design: DesignState, problems: tuple[Problem, ...]
    ) -> NormalizationFailureReview:
        return map_normalization_failure(design, problems, severities=settings, policies=policies)

    return map_failure


def map_normalization_failure(
    design: DesignState,
    problems: tuple[Problem, ...],
    *,
    severities: Mapping[str, Severity],
    policies: Mapping[str, RulePolicy] | None = None,
) -> NormalizationFailureReview:
    """정리 문제마다 규칙 지적 하나를 만든다. 문제를 빼거나 합치지 않는다.

    사람 확인 문제가 하나라도 있으면 `requires_manual_review=True`다. 지원하지 않는 문제 코드,
    FK 결정 번호, 입력 추적 세부 유형, 되짚을 수 없는 대상, 정하지 않은 심각도는 모두 멈춘다.
    """
    if not problems:
        raise ValueError("정리 실패에 문제 목록이 없습니다")
    targets = _TargetIndex(design)
    findings: list[Finding] = []
    manual = False
    for number, item in enumerate(problems, start=1):
        rule_code, kind, needs_person = _classify(item)
        objects = targets.resolve(item)
        severity = severities.get(rule_code)
        if severity is None:
            raise ValueError(f"{rule_code}의 심각도가 정해지지 않았습니다 (rules.yaml)")
        findings.append(
            Finding(
                id=f"{rule_code}-{design.iteration}-{number}",
                source=FindingSource.RULE,
                rule_code=rule_code,
                kind=kind,
                severity=severity,
                targets=objects,
                evidence=({"quote": item.detail},),  # 원문 인용이 아니라 정리 코드가 확인한 사실
                suggestion=_suggestion(kind),
                target_stage=None if needs_person else _stage(objects),
                fingerprint=fingerprint(rule_code, kind, objects),
                iteration=design.iteration,
            )
        )
        findings[-1], needs_person = apply_policy(
            findings[-1], policies or {}, inferred_manual=needs_person
        )
        manual = manual or needs_person
    return NormalizationFailureReview(findings=tuple(findings), requires_manual_review=manual)


def _classify(item: Problem) -> tuple[str, str, bool]:
    """(규칙 코드, 지적 종류, 사람 확인 여부). 지적 종류는 같은 대상의 다른 문제를 구분한다."""
    if item.code in _BY_DECISION:
        table = _BY_DECISION[item.code]
        if item.decision not in table:
            raise ValueError(
                f"{item.code.value}의 결정 번호를 알 수 없습니다: {item.decision!r} ({item.target})"
            )
        rule_code, needs_person = table[item.decision]
        return rule_code, f"{item.code.value}:{item.decision}", needs_person
    if item.code is ProblemCode.INPUT_TRACE:
        trace_kind = _trace_kind(item)
        rule_code = "RULE-02" if trace_kind == "missing_req_ids" else "RULE-01"
        return rule_code, f"{item.code.value}:{trace_kind}", False
    if item.code not in _RULES:
        raise ValueError(
            f"규칙 지적으로 바꾸지 않는 정리 문제입니다: {item.code.value} ({item.target})"
        )
    rule_code, needs_person = _RULES[item.code]
    return rule_code, item.code.value, needs_person


def _trace_kind(item: Problem) -> str:
    """입력 추적 문제의 세부 유형. 정리 코드가 `"{대상 종류} {세부 유형}: {설명}"`으로 적는다."""
    head = item.detail.split(":", 1)[0].split()
    if len(head) != 2 or head[0] not in _OBJECT_KINDS or head[1] not in _TRACE_KINDS:
        raise ValueError(f"입력 추적 문제의 세부 유형을 알 수 없습니다: {item.detail!r}")
    return head[1]


def _suggestion(kind: str) -> str:
    """지적 종류별 고정 안내 문장."""
    if kind.startswith(f"{ProblemCode.INPUT_TRACE.value}:"):
        return _TRACE_SUGGESTIONS[kind.split(":", 1)[1]]
    return _SUGGESTIONS[kind]


def _stage(objects: tuple[FindingTarget, ...]) -> TargetStage:
    """대상 중 가장 앞 단계로 돌아간다 (요구사항 → 기능 → 데이터 설계)."""
    order = list(TargetStage)
    return min((_STAGE_BY_KIND[o.kind] for o in objects), key=order.index)


# 문제 코드가 가리키는 대상의 종류. 정리 코드(`codegen/normalize.py`, `naming.py`)가 문제를 만들 때
# 넣는 ID와 맞춘다. "table"·"column"은 테이블·컬럼 ID를 원래 대상으로 되짚는다.
_TARGET_SPACES: dict[ProblemCode, tuple[str, ...]] = {
    ProblemCode.NO_PRIMARY_KEY: ("entity",),
    ProblemCode.IDENTIFYING_CYCLE: ("entity",),
    ProblemCode.DOMAIN_TYPE_MISMATCH: ("column",),
    ProblemCode.PARENT_WITHOUT_KEY: ("relationship",),
    ProblemCode.OPTIONAL_IDENTIFYING: ("relationship",),
    ProblemCode.REQUIRED_SELF_REFERENCE: ("relationship",),
    ProblemCode.UNSUPPORTED_RELATIONSHIP: ("relationship",),
    ProblemCode.NAMING_RULE_MISSING: ("relationship",),
    ProblemCode.FK_COLUMN_CONFLICT: ("relationship",),
    ProblemCode.UNRESOLVED_NAME: ("table", "column", "relationship"),  # 자기참조 접두어는 관계
    ProblemCode.NAME_TOO_LONG: ("table", "column", "relationship"),  # 자기참조 FK 칸은 관계
    ProblemCode.RESERVED_WORD: ("table", "column", "relationship"),
    ProblemCode.DUPLICATE_NAME: ("table",),
}


class _TargetIndex:
    """정리 문제의 대상 ID → 원래 요구사항·기능·엔티티·속성·관계.

    대상은 종류별로 따로 찾는다. 종류가 다른 객체가 같은 ID를 써도(계약이 허용) 섞이지 않는다.
    엔티티 테이블·속성 컬럼·N:M 연결 테이블 ID는 정리 코드와 같은 ID 계산으로 다시 만들어 찾는다.
    관계가 만드는 FK 컬럼은 정리 코드가 원래 관계 ID를 대상으로 넣으므로 되짚지 않는다. 그래서
    정리에서 막힌 관계의 키를 펼칠 일이 없다.
    """

    def __init__(self, design: DesignState) -> None:
        pack = design.versions.pack_id
        if pack is None:
            raise ValueError("정리 문제의 대상을 되짚을 팩 ID가 없습니다 (versions.pack_id)")
        self._design = design
        self._pack = pack
        spaces: dict[str, dict[str, list[FindingTarget]]] = {
            kind: {} for kind in ("requirement", "function", "entity", "attribute",
                                  "relationship", "table", "column")
        }  # fmt: skip

        def add(space: str, object_id: str, kind: ObjectKind, original: str) -> None:
            target = FindingTarget(kind=kind, id=original)
            found = spaces[space].setdefault(object_id, [])
            if target not in found:
                found.append(target)

        for r in design.requirements:
            add("requirement", r.id, "requirement", r.id)
        for f in design.functions:
            add("function", f.id, "function", f.id)
        for e in design.entities:
            add("entity", e.id, "entity", e.id)
            add("table", stable_id("TBL", pack, e.id), "entity", e.id)
            for a in e.attributes:
                add("attribute", a.id, "attribute", a.id)
                add("column", stable_id("COL", pack, a.id), "attribute", a.id)
        for rel in design.relationships:
            add("relationship", rel.id, "relationship", rel.id)
            if _makes_junction(rel):
                add("table", stable_id("TBL", pack, rel.id), "relationship", rel.id)
        self._spaces = spaces

    def resolve(self, item: Problem) -> tuple[FindingTarget, ...]:
        """문제 하나의 대상들. 하나라도 못 찾거나 두 대상에 걸리면 멈춘다."""
        if item.code is ProblemCode.INPUT_TRACE:
            spaces: tuple[str, ...] = (_trace_object_kind(item),)
        elif item.code in _TARGET_SPACES:
            spaces = _TARGET_SPACES[item.code]
        else:
            raise ValueError(f"대상을 되짚을 수 없는 정리 문제입니다: {item.code.value}")
        ids = [part for part in item.target.split(",") if part]
        if not ids:
            raise ValueError(f"정리 문제에 대상이 없습니다: {item.code.value}")
        resolved: list[FindingTarget] = []
        for object_id in ids:
            target = self._one(object_id, spaces, item)
            if target not in resolved:
                resolved.append(target)
        return tuple(resolved)

    def _one(self, object_id: str, spaces: tuple[str, ...], item: Problem) -> FindingTarget:
        found = [t for space in spaces for t in self._spaces[space].get(object_id, [])]
        if not found:
            raise ValueError(
                f"정리 문제의 대상을 원래 설계에서 찾지 못했습니다: {item.code.value} {object_id}"
            )
        if len(found) > 1:
            names = ", ".join(f"{t.kind} {t.id}" for t in found)
            raise ValueError(f"정리 문제의 대상 {object_id}가 여러 대상에 걸립니다: {names}")
        return found[0]


def _trace_object_kind(item: Problem) -> str:
    """입력 추적 문제의 대상 종류 (`_trace_kind`가 형식을 먼저 확인한다)."""
    return item.detail.split(":", 1)[0].split()[0]


def _makes_junction(rel: Relationship) -> bool:
    """정리 코드가 연결 테이블을 만드는 관계: 비식별 N:M이고 자기참조가 아니다 (`_accept`)."""
    return (
        rel.cardinality is Cardinality.MANY_TO_MANY
        and not rel.identifying
        and rel.parent != rel.child
    )
