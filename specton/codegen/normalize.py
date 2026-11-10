"""모델 정리 (#12): 엔티티·속성·관계 → 테이블·컬럼·PK·FK·연결 테이블. **임시 구현.**

처리 순서 (D14):
1. 엔티티마다 테이블을 만든다. 이때 PK 후보는 자기 키 속성뿐이다.
2. 식별 관계를 "부모 → 자식" 순서(위상 순서, 같은 단계는 엔티티 ID 순)로 따라가며 부모 PK 묶음
   전체를 자식 FK로 넣고, 자식 PK를 "부모 PK 칸(관계 ID 순) + 자기 키" 순서로 확정한다.
3. 모든 PK가 정해진 뒤 비식별 관계(1:N, 1:1, 자기참조)의 FK와 N:M 연결 테이블을 관계 ID 순으로
   만든다.

규칙 상태:
- 확정 (문서·PR): N:M은 연결 테이블 + FK 2개, 파생 객체는 원래 관계의 req_ids를 물려받음,
  도메인 이름·정밀도 보존, 63바이트 초과·예약어 거부, PK 없음은 차단 (RULE-03)
- R4 제안 (#12 확인 전): 이름 기반 해시 ID(D1), 파생 ID는 관계 ID + 부모 키 칸 ID(D3),
  FK 칸 이름 = 부모 키 이름(D4), 자기참조는 사전 단어 접두어(D4, naming.yaml
  `column.self_reference_prefix`), 연결 테이블 이름 = 부모 + 자식 테이블 이름(D4, naming.yaml
  `table.junction_name`), A04 인계 FK 규칙(D8), 선택+식별 충돌(D11),
  복합 키는 부모 PK 순서대로 짝(D12), 기존 속성 재사용 안 함(D13), 식별 관계 순서(D14)
- 한계: 관계 ID가 A04 순번(`REL-01`)이라, A04가 순번을 다시 매기면 파생 ID가 바뀐다 (D2)

문제는 끝까지 모두 모으고, 하나라도 있으면 `NormalizeFailed`만 돌려준다. 한 원인에서 이어지는
문제(막힌 부모의 자손)는 따로 보고하지 않는다. 입력은 바꾸지 않는다.
이 모듈은 LLM client를 import하지 않는다.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from specton.codegen.model import (
    RULES_VERSION,
    Column,
    ForeignKey,
    Normalized,
    NormalizedModel,
    NormalizeFailed,
    NormalizeResult,
    Problem,
    ProblemCode,
    Table,
    problem,
)
from specton.codegen.naming import Lexicon, NamingRules, check_name, physical_name, unresolved
from specton.contracts import DesignState, Entity, Relationship, find_trace_issues
from specton.contracts.base import Cardinality, SqlType
from specton.ids import stable_id

_TIME_TYPES = frozenset({SqlType.TIME, SqlType.TIMESTAMP, SqlType.TIMESTAMPTZ})
_FK_COPIED = ("data_type", "length", "precision", "scale", "time_precision", "domain")
_Bad = Callable[[str, str], None]  # check_output의 문제 기록 함수


@dataclass(frozen=True)
class PackRef:
    """정리에 쓰는 팩. 결과에 이름·버전을 남긴다."""

    name: str
    version: str


@dataclass
class _Run:
    """정리 한 번의 작업 상태. 함수 사이에 넘기는 값을 묶는다."""

    pack: PackRef
    lexicon: Lexicon
    rules: NamingRules
    tables: dict[str, Table]  # 엔티티 ID 또는 `rel:<관계 ID>`(연결 테이블) → 테이블
    problems: list[Problem] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    blocked: set[str] = field(default_factory=set)  # 앞선 원인으로 PK를 정할 수 없는 엔티티
    qualified_relationships: set[str] = field(default_factory=set)


def normalize(
    design: DesignState, *, pack: PackRef, lexicon: Lexicon, rules: NamingRules
) -> NormalizeResult:
    """설계 상태의 엔티티·관계를 정리한다. 같은 입력이면 항상 같은 결과다."""
    input_problems = _input_problems(design, pack)
    if input_problems:
        # 참조를 믿을 수 없으면 뒤 단계가 엉뚱한 문제를 쏟아내므로 여기서 멈춘다.
        return _failed(input_problems)

    run = _Run(pack, lexicon, rules, tables={})
    entities = sorted(design.entities, key=lambda e: e.id)
    own_keys: dict[str, tuple[str, ...]] = {}
    for entity in entities:
        run.tables[entity.id] = _entity_table(entity, run)
        own_keys[entity.id] = run.tables[entity.id].primary_key

    relationships = sorted(design.relationships, key=lambda r: _id_order(r.id))
    supported = [r for r in relationships if _accept(r, run)]
    run.qualified_relationships = _qualified_references(supported, rules)
    identifying = [r for r in supported if r.identifying]
    _resolve_primary_keys([e.id for e in entities], identifying, own_keys, run)
    for rel in supported:
        if not rel.identifying:
            _derive_non_identifying(rel, run)
    run.problems.extend(_duplicate_table_names(run.tables.values()))

    model = NormalizedModel(
        pack=pack.name,
        pack_version=pack.version,
        rules_version=RULES_VERSION,
        lexicon_digest=lexicon.digest,
        tables=tuple(sorted(run.tables.values(), key=lambda t: t.id)),
        foreign_keys=tuple(sorted(run.foreign_keys, key=lambda f: f.id)),
    )
    if run.problems:
        return _failed(run.problems)
    # 여기까지 문제가 없으면 결과를 한 번 더 검사한다 (코드 오류 방어, TC-N01).
    output_problems = check_output(model, design)
    if output_problems:
        return _failed(output_problems)
    return Normalized(model=model)


# ── 입력 ──────────────────────────────────────────────────────────────


def _input_problems(design: DesignState, pack: PackRef) -> list[Problem]:
    problems = [
        problem(ProblemCode.INPUT_TRACE, i.object_id, f"{i.object_kind} {i.kind}: {i.detail}")
        for i in find_trace_issues(design)
    ]
    problems.extend(
        problem(ProblemCode.PACK_MISMATCH, e.id, f"엔티티 팩 {e.pack} ≠ 정리 팩 {pack.name}")
        for e in design.entities
        if e.pack != pack.name
    )
    return problems


def _accept(rel: Relationship, run: _Run) -> bool:
    """처리할 수 없는 관계를 문제로 남기고 거른다."""
    self_ref = rel.parent == rel.child
    many = rel.cardinality is Cardinality.MANY_TO_MANY
    if rel.identifying and (self_ref or many):
        # A04 인계: 자기참조·N:M은 항상 비식별이다 (#79). 들어오면 처리하지 않는다.
        kind = "자기참조" if self_ref else "N:M"
        run.problems.append(_unsupported(rel, f"식별 {kind} 관계", decision="D8"))
        return False
    if self_ref and many:
        # 임시(#11): 자기참조 N:M의 연결 테이블에는 같은 테이블을 가리키는 FK 칸이 둘 생겨 상위·하위
        #   두 단어가 필요한데, 「하위」가 공통 단어 사전에 없고 지금 팩 패턴에도 없어 막는다.
        #   필요해지면 naming.yaml column에 키를 하나 더한다 (R2 답).
        run.problems.append(
            _unsupported(
                rel,
                "자기참조 N:M 관계 (연결 테이블 칸 이름 규칙 없음)",
                decision="D4",
                pending=True,
            )
        )
        return False
    if rel.identifying and rel.optional:
        run.problems.append(
            problem(
                ProblemCode.OPTIONAL_IDENTIFYING,
                rel.id,
                "식별 관계의 FK는 PK 일부라 비울 수 없는데 선택 관계로 들어옴",
                decision="D11",
            )
        )
        return False
    if self_ref and not rel.optional:
        run.problems.append(
            problem(
                ProblemCode.REQUIRED_SELF_REFERENCE,
                rel.id,
                "필수 자기참조는 FK가 NOT NULL이라 최상위 행(상위가 없는 행)을 넣을 수 없음",
            )
        )
        return False
    # 자기참조 FK 칸 접두어는 load_naming_rules가 naming.yaml `column.self_reference_prefix`
    # (사전 단어, 예: 상위 → UP)에서 읽어 온다. 빈칸(미정)이면 이름을 만들 수 없어 막는다.
    if self_ref and run.rules.self_reference_prefix is None:
        run.problems.append(
            problem(
                ProblemCode.NAMING_RULE_MISSING,
                rel.id,
                "자기참조 FK 칸 이름 규칙이 없음 (naming.yaml column.self_reference_prefix 빈칸)",
                decision="D4",
            )
        )
        return False
    return True


def _unsupported(
    rel: Relationship, reason: str, *, decision: str, pending: bool = False
) -> Problem:
    """처리하지 않는 관계. 원인을 `decision`으로 나눈다 (#15 R1 댓글 2번).

    - D8: A04 인계 규칙(#79) 위반(식별 자기참조·식별 N:M). 설계를 고치면 풀린다.
    - D4: 설계는 맞지만 지금 정리 코드가 이름을 지을 수 없음(자기참조 N:M). 지원 방안을 사람이
      정한다. 자동 재작업으로 관계의 업무 의미를 바꾸게 하지 않는다. `pending`=결정 대기.
    """
    return problem(
        ProblemCode.UNSUPPORTED_RELATIONSHIP, rel.id, reason, decision=decision, pending=pending
    )


# ── 테이블 ────────────────────────────────────────────────────────────


def _entity_table(entity: Entity, run: _Run) -> Table:
    """엔티티 → 테이블. PK는 자기 키 속성만 담고, 식별 관계 처리 뒤 확정한다."""
    pack = run.pack.name
    table_id = stable_id("TBL", pack, entity.id)
    table_name = _named(entity.name, table_id, run)
    columns: list[Column] = []
    for attr in entity.attributes:
        col_id = stable_id("COL", pack, attr.id)
        term = run.lexicon.term(attr.name)
        if term and term.data_type is not None and term.data_type is not attr.data_type:
            run.problems.append(
                problem(
                    ProblemCode.DOMAIN_TYPE_MISMATCH,
                    col_id,
                    f"{attr.name}: 속성 타입 {attr.data_type.value} ≠ 팩 용어 도메인 "
                    f"{term.domain}의 타입 {term.data_type.value}",
                )
            )
        columns.append(
            Column(
                id=col_id,
                name=attr.name,
                physical_name=_named(attr.name, col_id, run),
                data_type=attr.data_type,
                length=attr.length,
                precision=attr.precision,
                scale=attr.scale,
                time_precision=term.time_precision
                if term and attr.data_type in _TIME_TYPES
                else None,
                domain=term.domain if term else None,
                nullable=attr.nullable,
                req_ids=attr.req_ids,
                attribute_id=attr.id,
            )
        )
    run.problems.extend(_duplicate_column_names(table_id, columns))
    return Table(
        id=table_id,
        name=entity.name,
        physical_name=table_name,
        columns=tuple(columns),
        primary_key=tuple(stable_id("COL", pack, a.id) for a in entity.attributes if a.is_key),
        # 최종 PK와 같은 UNIQUE는 PK가 정해진 뒤 뺀다 (_resolve_primary_keys)
        unique_keys=tuple(
            (stable_id("COL", pack, a.id),) for a in entity.attributes if a.is_unique
        ),
        req_ids=entity.req_ids,
        entity_id=entity.id,
    )


def _named(logical: str, target: str, run: _Run) -> str:
    name = physical_name(logical, run.lexicon)
    if name is None:
        run.problems.append(unresolved(logical, target))
        return ""  # 결과는 실패로 끝나므로 빈 이름이 밖으로 나가지 않는다
    run.problems.extend(check_name(name, target, run.rules))
    return name


def _duplicate_column_names(table_id: str, columns: Iterable[Column]) -> Iterator[Problem]:
    counts = Counter(c.physical_name for c in columns if c.physical_name)
    for name in sorted(n for n, k in counts.items() if k > 1):
        yield problem(ProblemCode.DUPLICATE_NAME, table_id, f"컬럼 물리명 {name} 중복")


def _duplicate_table_names(tables: Iterable[Table]) -> Iterator[Problem]:
    by_name: dict[str, list[str]] = {}
    for t in tables:
        if t.physical_name:
            by_name.setdefault(t.physical_name, []).append(t.id)
    for name, ids in sorted(by_name.items()):
        if len(ids) > 1:
            yield problem(
                ProblemCode.DUPLICATE_NAME, ",".join(sorted(ids)), f"테이블 물리명 {name} 중복"
            )


# ── PK (식별 관계, D14) ───────────────────────────────────────────────


def _resolve_primary_keys(
    entity_ids: Sequence[str],
    identifying: Sequence[Relationship],
    own_keys: dict[str, tuple[str, ...]],
    run: _Run,
) -> None:
    """식별 관계 순서대로 자식 PK를 확정한다. 순환에 든 엔티티와 그 자손은 막는다."""
    order, cyclic = _identifying_order(entity_ids, identifying)
    if cyclic:
        run.problems.append(
            problem(
                ProblemCode.IDENTIFYING_CYCLE,
                ",".join(sorted(cyclic)),
                "식별 관계가 순환해 PK 순서를 정할 수 없음",
                decision="D14",
            )
        )
    run.blocked.update(set(entity_ids) - set(order))
    for entity_id in order:
        fk_columns: list[str] = []
        one_to_one: list[tuple[str, ...]] = []
        for rel in (r for r in identifying if r.child == entity_id):  # 관계 ID 순
            if rel.parent in run.blocked:
                run.blocked.add(entity_id)  # 원인은 부모 쪽에 이미 보고됨
                continue
            fk = _derive_fk(rel, entity_id, rel.parent, stable_id("FK", run.pack.name, rel.id), run)
            if fk is None:
                run.blocked.add(entity_id)
                continue
            fk_columns.extend(fk.columns)
            if rel.cardinality is Cardinality.ONE_TO_ONE:
                one_to_one.append(fk.columns)
        if entity_id in run.blocked:
            continue
        primary_key = (*fk_columns, *own_keys[entity_id])
        table = run.tables[entity_id]
        if not primary_key:
            run.problems.append(
                problem(
                    ProblemCode.NO_PRIMARY_KEY,
                    entity_id,
                    f"{table.name}: 키 속성(is_key)도 식별 관계도 없음 (RULE-03)",
                    decision="D6",
                )
            )
            run.blocked.add(entity_id)  # 이 엔티티를 부모로 둔 관계는 따로 보고하지 않는다
        # 최종 PK(물려받은 부모 키 포함)와 같은 UNIQUE는 이미 유일하므로 뺀다
        unique = tuple(u for u in (*table.unique_keys, *one_to_one) if u != primary_key)
        run.tables[entity_id] = table.model_copy(
            update={"primary_key": primary_key, "unique_keys": unique}
        )


def _identifying_order(
    entity_ids: Sequence[str], identifying: Sequence[Relationship]
) -> tuple[list[str], set[str]]:
    """식별 관계의 위상 순서와 순환에 든 엔티티. 같은 단계는 엔티티 ID 순이다."""
    parents: dict[str, set[str]] = {e: set() for e in entity_ids}
    children: dict[str, set[str]] = {e: set() for e in entity_ids}
    for rel in identifying:
        parents[rel.child].add(rel.parent)
        children[rel.parent].add(rel.child)
    waiting = {e: len(p) for e, p in parents.items()}
    ready = sorted(e for e, n in waiting.items() if n == 0)
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for child in children[current]:
            waiting[child] -= 1
            if waiting[child] == 0:
                ready.append(child)
        ready.sort()
    # 남은 것은 순환에 든 엔티티와, 순환 뒤에 이어져 순서를 정할 수 없는 엔티티다.
    # 순환의 원인으로는 자식 쪽으로 따라가 자기 자신에게 돌아오는 엔티티만 보고한다.
    # 두 순환 사이를 잇기만 하는 엔티티는 막히지만 원인 목록에는 넣지 않는다.
    rest = set(entity_ids) - set(order)
    cyclic = {e for e in rest if e in _reachable(children, children[e] & rest, rest)}
    return order, cyclic


def _reachable(children: dict[str, set[str]], start: set[str], within: set[str]) -> set[str]:
    """`start`에서 자식 쪽으로 `within` 안에서만 따라가 닿는 엔티티."""
    seen: set[str] = set()
    stack = sorted(start)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(sorted((children[current] & within) - seen))
    return seen


# ── FK ───────────────────────────────────────────────────────────────


def _derive_non_identifying(rel: Relationship, run: _Run) -> None:
    """비식별 관계: 1:N·1:1·자기참조는 자식 FK, N:M은 연결 테이블."""
    sides = (rel.parent, rel.child)
    if any(e in run.blocked for e in sides):
        return  # 원인은 막힌 엔티티 쪽에 이미 보고됨
    if rel.cardinality is Cardinality.MANY_TO_MANY:
        _derive_junction(rel, run)
        return
    fk = _derive_fk(rel, rel.child, rel.parent, stable_id("FK", run.pack.name, rel.id), run)
    if fk is None or rel.cardinality is not Cardinality.ONE_TO_ONE:
        return
    child = run.tables[rel.child]
    if fk.columns != child.primary_key and fk.columns not in child.unique_keys:
        # 1:1은 자식 한 건에 부모 한 건이라 FK 묶음에 UNIQUE (D8). PK와 같으면 이미 유일하다.
        run.tables[rel.child] = child.model_copy(
            update={"unique_keys": (*child.unique_keys, fk.columns)}
        )


def _derive_junction(rel: Relationship, run: _Run) -> None:
    """N:M → 연결 테이블. 부모 쪽 FK 칸, 자식 쪽 FK 칸 순서로 함께 PK가 된다."""
    parent, child = run.tables[rel.parent], run.tables[rel.child]
    missing = [t for t in (parent, child) if not t.primary_key]
    for t in missing:
        run.problems.append(
            problem(ProblemCode.PARENT_WITHOUT_KEY, rel.id, f"{t.name}에 PK가 없어 연결할 수 없음")
        )
    if missing:
        return
    key = f"rel:{rel.id}"
    table_id = stable_id("TBL", run.pack.name, rel.id)
    physical = ""
    if parent.physical_name and child.physical_name:  # 빈 이름은 이미 D5 문제로 보고됨
        physical = _junction_name(parent, child, run.rules)
        run.problems.extend(check_name(physical, table_id, run.rules))
    run.tables[key] = Table(
        id=table_id,
        name=f"{parent.name}{child.name}",
        physical_name=physical,
        columns=(),
        primary_key=(),
        unique_keys=(),
        req_ids=rel.req_ids,  # 파생 객체는 원래 관계의 req_ids를 물려받는다
        relationship_id=rel.id,
    )
    columns: list[str] = []
    for side in (rel.parent, rel.child):
        fk = _derive_fk(rel, key, side, stable_id("FK", run.pack.name, rel.id, side), run)
        if fk is None:
            return
        columns.extend(fk.columns)
    run.tables[key] = run.tables[key].model_copy(update={"primary_key": tuple(columns)})


def _junction_name(parent: Table, child: Table, rules: NamingRules) -> str:
    """연결 테이블 물리명 (naming.yaml `table.junction_name`).

    `parent_child`와 미정(None)은 같은 동작이다: 부모 테이블 물리명 + 자식 테이블 물리명 (D4).
    다른 값은 load_naming_rules가 이미 거절했다.
    """
    if rules.junction_name not in (None, "parent_child"):
        raise ValueError(f"알 수 없는 연결 테이블 이름 규칙: {rules.junction_name}")
    return rules.separator.join((parent.physical_name, child.physical_name))


def _derive_fk(
    rel: Relationship, target: str, parent_key: str, fk_id: str, run: _Run
) -> ForeignKey | None:
    """`parent_key` 테이블의 PK 묶음 전체를 `target` 테이블에 FK 칸으로 더한다 (D12).

    칸 이름은 부모 키 이름이고(D4), 자기참조면 사전 단어 접두어를 붙인다. 이름이 대상 테이블의
    칸과 겹치면 재사용하지 않고 충돌로 보고한다(D4·D13).
    """
    parent, table = run.tables[parent_key], run.tables[target]
    if not parent.primary_key:
        run.problems.append(
            problem(ProblemCode.PARENT_WITHOUT_KEY, rel.id, f"부모 {parent.name}에 PK가 없음")
        )
        return None
    prefix: tuple[str, str] | None = None
    if rel.parent == rel.child:
        prefix = _self_reference_prefix(rel, run)
        if prefix is None:
            return None
    parent_cols = {c.id: c for c in parent.columns}
    taken = {c.physical_name: c for c in table.columns}
    taken_logical = {c.name: c for c in table.columns}
    new_columns: list[Column] = []
    conflict = False
    for parent_col_id in parent.primary_key:  # 부모 PK 순서대로 (D12)
        key = parent_cols[parent_col_id]
        col_id = stable_id("COL", run.pack.name, rel.id, key.id)
        name, physical = key.name, key.physical_name
        if prefix is not None:
            name = f"{prefix[0]}{key.name}"
            if physical:
                physical = run.rules.separator.join((prefix[1], physical))
                # 대상은 이 FK 칸을 만든 관계다. 정리에 실패하면 칸이 만들어지지 않으므로,
                # 실패 변환기(#15)가 칸 ID를 되짚지 않고 원래 관계로 바로 잇게 한다.
                run.problems.extend(check_name(physical, rel.id, run.rules))
        name, physical = _qualified_key_name(rel, name, physical, run)
        # 빈 물리명은 이미 D5 문제로 보고된 자리표시라 서로 겹친다고 보지 않는다
        clash = (taken.get(physical) if physical else None) or taken_logical.get(name)
        if clash is not None:
            conflict = True
            run.problems.append(_fk_conflict(rel, table, physical, clash))
            continue
        column = Column(
            id=col_id,
            name=name,
            physical_name=physical,
            data_type=key.data_type,
            length=key.length,
            precision=key.precision,
            scale=key.scale,
            time_precision=key.time_precision,
            domain=key.domain,
            # 식별 관계·연결 테이블 칸은 PK라 NOT NULL. 그 밖에는 선택 관계면 NULL 허용 (D8)
            nullable=rel.optional and not rel.identifying and target == rel.child,
            req_ids=rel.req_ids,  # 파생 객체는 원래 관계의 req_ids를 물려받는다
            relationship_id=rel.id,
            references=key.id,
        )
        new_columns.append(column)
        taken_logical[name] = column
        if physical:
            taken[physical] = column
    if conflict:
        return None
    run.tables[target] = table.model_copy(update={"columns": (*table.columns, *new_columns)})
    fk = ForeignKey(
        id=fk_id,
        relationship_id=rel.id,
        table_id=table.id,
        columns=tuple(c.id for c in new_columns),
        parent_table_id=parent.id,
        parent_columns=parent.primary_key,
        req_ids=rel.req_ids,
    )
    run.foreign_keys.append(fk)
    return fk


def _qualified_references(relationships: Sequence[Relationship], rules: NamingRules) -> set[str]:
    if rules.repeated_foreign_key not in (None, "manual", "relationship_id"):
        raise ValueError("지원하지 않는 repeated_foreign_key 정책")
    if rules.repeated_foreign_key != "relationship_id":
        return set()
    references = [r for r in relationships if r.cardinality != "N:M"]
    pairs = Counter((r.parent, r.child) for r in references)
    return {r.id for r in references if pairs[r.parent, r.child] > 1}


def _qualified_key_name(rel: Relationship, name: str, physical: str, run: _Run) -> tuple[str, str]:
    """관계 의미는 그대로 두고 같은 부모 참조의 모든 FK를 안정적인 ID로 구분한다."""
    if rel.id not in run.qualified_relationships:
        return name, physical
    if physical:
        suffix = "r" + stable_id("REF", rel.id).split("-", 1)[1]
        physical = run.rules.separator.join((physical, suffix))
        run.problems.extend(check_name(physical, rel.id, run.rules))
    return f"{name}({rel.id})", physical


def _self_reference_prefix(rel: Relationship, run: _Run) -> tuple[str, str] | None:
    """자기참조 FK 칸의 (논리 접두어, 물리 접두어). 만들 수 없으면 문제를 남기고 None."""
    word = run.rules.self_reference_prefix
    if word is None:  # _accept에서 이미 문제로 남기고 걸렀다
        return None
    physical = physical_name(word, run.lexicon)
    if physical is None:
        run.problems.append(unresolved(word, rel.id))
        return None
    return word, physical


def _fk_conflict(rel: Relationship, table: Table, physical: str, clash: Column) -> Problem:
    if clash.relationship_id is not None:
        # 같은 테이블에 같은 이름의 FK 칸을 만드는 관계가 또 있음 → 이름 구분 규칙이 필요 (D4, D2)
        # 임시(#11): 역할 단어(출발·도착)로 구분하려면 A04 관계 출력에 칸을 더하는 계약 변경이
        #   필요해 후속으로 둔다 (#11 질문 3). 그때까지는 겹친 이름으로 모델을 만들지 않고 멈춘다.
        return problem(
            ProblemCode.FK_COLUMN_CONFLICT,
            rel.id,
            f"{table.name}.{physical}: 관계 {clash.relationship_id}의 FK 칸과 이름이 같음. "
            "같은 이름의 부모 키를 두 번 가리키는 관계라(예: 출발 창고·도착 창고) "
            "역할 구분이 필요합니다",
            decision="D4",
        )
    # 기존 속성과 이름이 같음. 같은 대상을 가리킨다는 근거가 없어 재사용하지 않는다 (D13)
    return problem(
        ProblemCode.FK_COLUMN_CONFLICT,
        rel.id,
        f"{table.name}.{physical}: 기존 속성 {clash.name}과 이름이 같음 (재사용 근거 없음)",
        decision="D13",
    )


# ── 출력 검사 ─────────────────────────────────────────────────────────


def check_output(model: NormalizedModel, design: DesignState) -> list[Problem]:
    """결과 모델의 참조·출처·완전성·추적을 모두 검사한다 (TC-N01, 정리 코드의 실수 방어).

    ID 중복, 없는 테이블·컬럼·입력 객체 참조, 출처 누락·중복, 빠진 테이블·FK, PK 칸 NULL 허용,
    FK 칸과 부모 칸의 짝·타입, req_ids 누락·없는 REQ를 찾는다.
    """
    found: list[Problem] = []
    req_ids = frozenset(r.id for r in design.requirements)
    entity_attrs = {e.id: frozenset(a.id for a in e.attributes) for e in design.entities}
    relationships = {r.id: r for r in design.relationships}
    tables = {t.id: t for t in model.tables}

    def bad(target: str, detail: str) -> None:
        found.append(problem(ProblemCode.OUTPUT_TRACE, target, detail))

    for kind, ids in (
        ("테이블", [t.id for t in model.tables]),
        ("컬럼", [c.id for t in model.tables for c in t.columns]),
        ("FK", [f.id for f in model.foreign_keys]),
    ):
        for dup in sorted(i for i, n in Counter(ids).items() if n > 1):
            bad(dup, f"{kind} ID 중복")

    for table in model.tables:
        _check_table(table, entity_attrs, relationships, req_ids, bad, found)

    for fk in model.foreign_keys:
        if fk.relationship_id not in relationships:
            bad(fk.id, f"없는 관계 {fk.relationship_id}")
        child, parent = tables.get(fk.table_id), tables.get(fk.parent_table_id)
        if child is None:
            bad(fk.id, f"없는 테이블 {fk.table_id}")
        if parent is None:
            bad(fk.id, f"없는 부모 테이블 {fk.parent_table_id}")
        if len(fk.columns) != len(fk.parent_columns) or not fk.columns:
            bad(fk.id, "FK 칸 수와 부모 칸 수가 다름")
        if parent is not None and fk.parent_columns != parent.primary_key:
            bad(fk.id, "부모 칸이 부모 PK 묶음과 다름")
        if child is not None:
            parent_cols = {c.id: c for c in parent.columns} if parent else {}
            _check_fk_columns(fk, child, parent_cols, bad)
        found.extend(_req_problems(fk.id, fk.req_ids, req_ids))

    _check_coverage(model, design, bad)
    return found


def _check_table(
    table: Table,
    entity_attrs: dict[str, frozenset[str]],
    relationships: dict[str, Relationship],
    req_ids: frozenset[str],
    bad: _Bad,
    found: list[Problem],
) -> None:
    columns = {c.id: c for c in table.columns}
    if table.entity_id is None and table.relationship_id is None:
        bad(table.id, "출처(엔티티·관계) 참조가 없음")
    if table.entity_id is not None and table.relationship_id is not None:
        bad(table.id, "출처(엔티티·관계)가 둘 다 있음")
    if table.entity_id is not None and table.entity_id not in entity_attrs:
        bad(table.id, f"없는 엔티티 {table.entity_id}")
    if table.relationship_id is not None and table.relationship_id not in relationships:
        bad(table.id, f"없는 관계 {table.relationship_id}")
    own_attrs = entity_attrs.get(table.entity_id or "", frozenset())
    for group_name, group in (
        ("PK", table.primary_key),
        *(("UNIQUE", u) for u in table.unique_keys),
    ):
        if not group:
            bad(table.id, f"빈 {group_name} 묶음")
        for col_id in group:
            if col_id not in columns:
                bad(table.id, f"{group_name}가 없는 컬럼 {col_id}을 가리킴")
    for col_id in table.primary_key:
        if col_id in columns and columns[col_id].nullable:
            bad(table.id, f"PK 칸 {col_id}이 NULL 허용")
    found.extend(_req_problems(table.id, table.req_ids, req_ids))
    for col in table.columns:
        if col.attribute_id is None and col.relationship_id is None:
            bad(col.id, "출처(속성·관계) 참조가 없음")
        if col.attribute_id is not None and col.relationship_id is not None:
            bad(col.id, "출처(속성·관계)가 둘 다 있음")
        if col.attribute_id is not None and col.attribute_id not in own_attrs:
            bad(col.id, f"테이블의 엔티티에 없는 속성 {col.attribute_id}")
        if col.relationship_id is not None and col.relationship_id not in relationships:
            bad(col.id, f"없는 관계 {col.relationship_id}")
        found.extend(_req_problems(col.id, col.req_ids, req_ids))


def _check_fk_columns(
    fk: ForeignKey, child: Table, parent_cols: dict[str, Column], bad: _Bad
) -> None:
    child_cols = {c.id: c for c in child.columns}
    for i, col_id in enumerate(fk.columns):
        col = child_cols.get(col_id)
        if col is None:
            bad(fk.id, f"자식 테이블에 없는 컬럼 {col_id}")
            continue
        if col.relationship_id != fk.relationship_id:
            # 자식에 있는 칸이어도 이 관계에서 만든 칸이 아니면 FK 칸이 아니다
            bad(fk.id, f"FK 칸 {col_id}이 관계 {fk.relationship_id}에서 만든 칸이 아님")
            continue
        expected = fk.parent_columns[i] if i < len(fk.parent_columns) else None
        if col.references != expected:
            bad(fk.id, f"FK 칸 {col_id}의 짝이 부모 칸 {expected}이 아님")
            continue
        parent = parent_cols.get(expected or "")
        if parent is not None and any(getattr(col, f) != getattr(parent, f) for f in _FK_COPIED):
            bad(fk.id, f"FK 칸 {col_id}의 타입이 부모 칸 {expected}과 다름")


def _check_coverage(model: NormalizedModel, design: DesignState, bad: _Bad) -> None:
    """입력 엔티티·관계마다 테이블·FK가 빠짐없이 한 번씩 있는지 본다."""
    by_entity = Counter(t.entity_id for t in model.tables if t.entity_id is not None)
    by_junction = Counter(t.relationship_id for t in model.tables if t.relationship_id is not None)
    fks = Counter(f.relationship_id for f in model.foreign_keys)
    for entity in design.entities:
        if by_entity[entity.id] != 1:
            bad(entity.id, f"엔티티 테이블이 {by_entity[entity.id]}개")
    for rel in design.relationships:
        many = rel.cardinality is Cardinality.MANY_TO_MANY
        if by_junction[rel.id] != (1 if many else 0):
            bad(rel.id, f"연결 테이블이 {by_junction[rel.id]}개")
        if fks[rel.id] != (2 if many else 1):
            bad(rel.id, f"FK가 {fks[rel.id]}개")


# ── 공통 ──────────────────────────────────────────────────────────────


def _id_order(object_id: str) -> tuple[str, int, str]:
    """`REL-9` < `REL-10`처럼 끝 번호를 숫자로 비교하는 정렬 키."""
    head, _, tail = object_id.rpartition("-")
    return (head, int(tail), "") if tail.isdigit() else (object_id, -1, object_id)


def _req_problems(target: str, ids: Sequence[str], known: frozenset[str]) -> Iterator[Problem]:
    if not ids:
        yield problem(ProblemCode.OUTPUT_TRACE, target, "req_ids가 비어 있음")
    for req in ids:
        if req not in known:
            yield problem(ProblemCode.OUTPUT_TRACE, target, f"없는 요구사항 {req}")


def _failed(problems: Iterable[Problem]) -> NormalizeFailed:
    ordered = sorted(set(problems), key=lambda p: (p.code.value, p.target, p.detail))
    return NormalizeFailed(problems=tuple(ordered))
