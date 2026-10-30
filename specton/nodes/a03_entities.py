"""A03 엔티티·속성·CRUD 설계 (04 문서, REQ-07, TC-A03).

요구사항과 A02 기능으로 엔티티·속성·기능별 CRUD를 LLM이 판단한다.
- 엔티티·속성 이름은 한글로 받는다 (임시 가정, 표기 확정 전). 엔티티 ID와 FK는 LLM이 쓰지 않는다.
- 기능은 입력의 기능 ID로, 엔티티는 같은 출력의 이름으로 가리킨다. 어기면 공통 client가 재요청한다.
- 엔티티·속성 ID는 팩·이름에서 계산한다. 재실행·삭제 후에도 같은 이름은 같은 ID,
  다른 이름은 다른 ID다.
  한계: 같은 이름은 같은 객체로 보고, 이름이 바뀌면 새 객체로 본다 (최종 형식은 #12).
- 다시 실행하면 `entity_ops`는 누적하지 않고 새 결과로 바꾼다.
- 팩 타입은 strict 프로필로 읽는다 (프로필 확정 전).
"""

import hashlib
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any, Self

from pydantic import Field, model_validator

from specton.config import Settings
from specton.contracts import (
    AttributeDraft,
    Crud,
    DesignState,
    Entity,
    EntityDesignDraft,
    EntityDraft,
    EntityOp,
    Function,
    SqlType,
)
from specton.contracts.base import Contract, NonEmptyText
from specton.llm.client import LLMClient
from specton.nodes.common import NodeRun, build_request
from specton.packs.build import DEFAULT_ROOT, read_yaml
from specton.packs.examples import load_examples

PROMPT_VERSION = "a03-v1"
SYSTEM_PROMPT = """\
너는 업무 시스템의 데이터 모델 설계자다.
요구사항과 기능으로 저장할 엔티티·속성과 기능별 CRUD를 정한다.

엔티티:
- name은 한글 논리명(예: 창고, 수불내역)이고, 같은 출력 안에서 겹치지 않는다.
- 요구사항에 저장 근거가 있는 것만 엔티티로 만든다. description에 무엇을 저장하는지 쓴다.
- req_ids에는 그 엔티티의 근거 요구사항 id만 입력에서 골라 적는다.

속성:
- pack.terms에 맞는 용어가 있으면 그 term을 name으로 쓰고
  data_type·length·precision·scale을 그대로 쓴다.
  맞는 용어가 없으면 요구사항에 근거해 직접 정하되, 없는 타입을 만들지 않는다.
- 업무 키는 is_key=true이고 nullable=false다. 키가 아닌 값의 중복을 막아야 하면 is_unique=true다.
- 필수 입력이라고 요구사항에 있는 속성만 nullable=false로 한다.
- 값의 범위·형식 제약은 쓰지 않는다. 속성마다 req_ids를 적는다.

기능별 CRUD(entity_ops):
- function_id에는 입력 functions의 id를, entity_name에는 이 출력의 엔티티 name을 쓴다.
- operations는 그 기능이 그 엔티티에 하는 조작(C 등록, R 조회, U 수정, D 삭제)만 중복 없이 적는다.
- 같은 기능과 엔티티의 쌍은 한 번만 적는다. 기능이 다루지 않는 엔티티는 적지 않는다.
- 모든 엔티티에 CRUD 네 가지를 채우지 않는다. 요구사항에 없는 조작을 지어내지 않는다.

CRUD 면제(crud_exemptions):
- 삭제하지 않고 사용 중지하는 엔티티, 확정 후 고치지 않는 이력 엔티티처럼 일부 조작을 제공하지 않는
  근거가 요구사항에 있을 때만 쓴다. reason은 pack.crud_exemption_reasons의 키 중 하나다.
- operation은 그 reason에 나열된 조작만 쓴다. 면제한 조작은 그 엔티티의 operations에 넣지 않는다.

출력하지 않는 것: 엔티티·속성 ID, FK(외래키) 속성, 관계, 값 범위 제약."""


class A03Output(EntityDesignDraft):
    """A03 LLM 출력. 중복 조작은 지우지 않고 거절해 재요청한다 (EntityOp 변환에서 실패하지 않게)."""

    @model_validator(mode="after")
    def _check_names_and_ops(self) -> Self:
        names = [e.name for e in self.entities]
        duplicated = sorted({n for n in names if names.count(n) > 1})
        if duplicated:
            raise ValueError(f"엔티티 이름이 중복됩니다: {', '.join(duplicated)}")
        for entity in self.entities:
            attr_names = [a.name for a in entity.attributes]
            same = sorted({n for n in attr_names if attr_names.count(n) > 1})
            if same:
                raise ValueError(f"{entity.name}의 속성 이름이 중복됩니다: {', '.join(same)}")
        unknown = sorted({op.entity_name for op in self.entity_ops} - set(names))
        if unknown:
            raise ValueError(f"entity_ops가 출력에 없는 엔티티를 가리킵니다: {', '.join(unknown)}")
        pairs = [(op.function_id, op.entity_name) for op in self.entity_ops]
        repeated = sorted({f"{f}/{n}" for f, n in pairs if pairs.count((f, n)) > 1})
        if repeated:
            raise ValueError(f"같은 기능·엔티티 쌍이 중복됩니다: {', '.join(repeated)}")
        same_ops = [
            f"{op.function_id}/{op.entity_name}"
            for op in self.entity_ops
            if len(set(op.operations)) != len(op.operations)
        ]
        if same_ops:
            raise ValueError(f"operations에 중복이 있습니다: {', '.join(same_ops)}")
        contradicted = [
            f"{entity.name}.{x.operation.value}"
            for entity in self.entities
            for x in entity.crud_exemptions
            if any(
                x.operation in op.operations
                for op in self.entity_ops
                if op.entity_name == entity.name
            )
        ]
        if contradicted:
            raise ValueError(f"면제한 조작이 entity_ops에 있습니다: {', '.join(contradicted)}")
        return self


class PackTerm(Contract):
    """LLM에 보여 줄 팩 용어. 팩 도메인을 계약 필드로 바꾸는 일은 호출자가 한다 (numeric 등)."""

    term: NonEmptyText
    data_type: SqlType
    length: int | None = Field(default=None, ge=1)
    precision: int | None = Field(default=None, ge=1)
    scale: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_type_params(self) -> Self:
        """LLM이 따라 쓸 값이므로 `AttributeDraft`가 거절할 조합은 팩 단계에서 막는다."""
        AttributeDraft(
            name=self.term,
            data_type=self.data_type,
            length=self.length,
            precision=self.precision,
            scale=self.scale,
            req_ids=("REQ-00",),  # 형식만 맞춘 자리표시
        )
        return self


def input_data(
    state: DesignState,
    *,
    terms: Sequence[PackTerm],
    exemption_reasons: Mapping[str, Sequence[Crud]],
) -> dict[str, Any]:
    """LLM에 보여 줄 요구사항·기능·팩 정보. few-shot 예시의 `input`도 이 모양으로 쓴다.

    우선순위는 구조를 정하지 않으므로 기능에서 뺀다. 팩 값은 코드에 두지 않고 호출자가 읽어 넘긴다.
    `exemption_reasons`는 면제 사유별로 면제할 수 있는 조작이다.
    """
    return {
        "requirements": [
            {"id": r.id, "type": r.type.value, "nfr_category": r.nfr_category, "text": r.text}
            for r in state.requirements
        ],
        "functions": [
            f.model_dump(mode="json", include={"id", "name", "description", "req_ids"})
            for f in state.functions
        ],
        "pack": {
            "terms": [t.model_dump(mode="json", exclude_none=True) for t in terms],
            "crud_exemption_reasons": {
                reason: [op.value for op in ops] for reason, ops in exemption_reasons.items()
            },
        },
    }


def _checked_against(
    function_ids: Collection[str],
    req_ids: Collection[str],
    terms: Sequence[PackTerm],
    exemption_reasons: Mapping[str, Collection[Crud]],
) -> type[A03Output]:
    """이번 입력으로 검사하는 출력 모델. 어기면 형식 오류처럼 재요청 대상이 된다.

    팩 용어와 이름이 같은 속성만 타입을 대조하고, 팩에 없는 속성은 허용한다.
    면제 사유는 팩이 인정하는 것만, 면제 조작은 그 사유에 나열된 것만 허용한다.
    """
    by_term = {t.term: t for t in terms}

    class CheckedA03Output(A03Output):
        @model_validator(mode="after")
        def _check_against_input(self) -> Self:
            unknown_functions = sorted(
                {op.function_id for op in self.entity_ops} - set(function_ids)
            )
            if unknown_functions:
                raise ValueError(f"입력에 없는 기능을 참조했습니다: {', '.join(unknown_functions)}")
            referenced = {r for e in self.entities for r in e.req_ids} | {
                r for e in self.entities for a in e.attributes for r in a.req_ids
            }
            unknown_reqs = sorted(referenced - set(req_ids))
            if unknown_reqs:
                raise ValueError(f"입력에 없는 요구사항을 참조했습니다: {', '.join(unknown_reqs)}")
            reasons = sorted(
                {x.reason for e in self.entities for x in e.crud_exemptions}
                - exemption_reasons.keys()
            )
            if reasons:
                allowed = ", ".join(sorted(exemption_reasons))
                raise ValueError(
                    f"허용되지 않는 면제 사유입니다: {', '.join(reasons)} (허용: {allowed})"
                )
            wrong_ops = [
                f"{e.name}.{x.operation.value}({x.reason})"
                for e in self.entities
                for x in e.crud_exemptions
                if x.operation not in exemption_reasons[x.reason]
            ]
            if wrong_ops:
                raise ValueError(f"사유가 면제할 수 없는 조작입니다: {', '.join(wrong_ops)}")
            mismatched = [
                f"{e.name}.{a.name}"
                for e in self.entities
                for a in e.attributes
                if a.name in by_term and not _same_type(a, by_term[a.name])
            ]
            if mismatched:
                raise ValueError(f"팩 용어와 타입·길이가 다릅니다: {', '.join(mismatched)}")
            return self

    return CheckedA03Output


def _same_type(attribute: AttributeDraft, term: PackTerm) -> bool:
    return (attribute.data_type, attribute.length, attribute.precision, attribute.scale) == (
        term.data_type,
        term.length,
        term.precision,
        term.scale,
    )


class A03Result(Contract):
    """A03 결과. 엔티티와 그에 맞춰 `entity_ops`가 채워진 기능은 함께 상태에 반영해야 한다."""

    entities: tuple[Entity, ...]
    functions: tuple[Function, ...]


class PackContext(Contract):
    """팩에서 읽은 A03 입력. `exemption_reasons`는 사유별로 면제할 수 있는 조작이다."""

    terms: tuple[PackTerm, ...]
    exemption_reasons: dict[str, tuple[Crud, ...]]


def load_pack_context(pack: str, *, root: Path = DEFAULT_ROOT) -> PackContext:
    """팩의 용어·도메인(strict)과 공통 면제 사유를 읽는다."""
    domains = {d["name"]: d for d in read_yaml(root / "common" / "domains.yaml")["domains"]}
    terms = tuple(
        PackTerm.model_validate(
            {"term": t["term"], **_contract_fields(domains[t["domain"]]["postgres"]["strict"])}
        )
        for t in read_yaml(root / pack / "terms.yaml")["terms"]
    )
    reasons = read_yaml(root / "common" / "rules.yaml")["crud_exemption_reasons"]
    return PackContext(terms=terms, exemption_reasons=reasons)


def _contract_fields(strict: Mapping[str, Any]) -> dict[str, Any]:
    """도메인의 strict 타입을 `AttributeDraft` 필드로 옮긴다.

    numeric의 길이는 precision으로 옮기고, 시각 타입의 precision은 비운다 (#12에서 보존 방식 결정).
    """
    kind = strict["type"]
    if kind in ("char", "varchar"):
        fields: dict[str, Any] = {"length": strict["length"]}
    elif kind == "numeric":
        fields = {"precision": strict["length"], "scale": strict.get("scale")}
    else:
        fields = {}
    return {"data_type": kind, **{k: v for k, v in fields.items() if v is not None}}


def run(
    client: LLMClient,
    state: DesignState,
    settings: Settings,
    *,
    pack: str,
    token_budget: int | None = None,
) -> NodeRun[A03Result]:
    """요구사항·기능으로 엔티티를 설계하고 코드가 ID를 붙여 기능의 `entity_ops`를 채운다."""
    if not state.requirements:
        raise ValueError("A03: 엔티티를 설계할 요구사항이 없습니다")
    if not state.functions:
        raise ValueError("A03: 엔티티를 설계할 기능이 없습니다")
    context = load_pack_context(pack)
    request = build_request(
        settings,
        role="design",
        stage="A03",
        prompt_version=PROMPT_VERSION,
        system=SYSTEM_PROMPT,
        data=input_data(state, terms=context.terms, exemption_reasons=context.exemption_reasons),
        examples=load_examples(pack, "A03", A03Output),
    )
    output_model = _checked_against(
        {f.id for f in state.functions},
        {r.id for r in state.requirements},
        context.terms,
        context.exemption_reasons,
    )
    result = client.complete(request, output_model, token_budget=token_budget)
    draft = result.output
    entities = _with_ids(draft.entities, pack)
    id_by_name = {e.name: e.id for e in entities}
    ops_by_function: dict[str, list[EntityOp]] = {}
    for op in draft.entity_ops:
        ops_by_function.setdefault(op.function_id, []).append(
            EntityOp(entity_id=id_by_name[op.entity_name], operations=op.operations)
        )
    functions = tuple(
        f.evolve(entity_ops=tuple(ops_by_function.get(f.id, ()))) for f in state.functions
    )
    return NodeRun(output=A03Result(entities=entities, functions=functions), calls=result.calls)


# 해시 앞 16자리(64비트). 한 실행의 엔티티·속성 수에서 충돌 확률은 무시할 만하고, 나면 멈춘다.
_ID_HEX_LENGTH = 16


def _with_ids(drafts: Sequence[EntityDraft], pack: str) -> tuple[Entity, ...]:
    """팩·이름으로 계산한 ID를 붙인다. 재작업에서도 같은 객체의 ID를 유지한다 (05 문서 "ID·추적").

    LLM은 ID를 쓰지 않으므로 같은 의미는 이름으로 판단한다. 순번과 달리 직전 상태에 의존하지 않아,
    삭제된 객체의 ID가 다른 객체에 다시 쓰이지 않는다.
    """
    entities = tuple(
        Entity.model_validate(
            {
                **d.model_dump(exclude={"attributes"}),
                "id": _stable_id("ENT", pack, d.name),
                "pack": pack,
                "attributes": [
                    {**a.model_dump(), "id": _stable_id("ATTR", pack, d.name, a.name)}
                    for a in d.attributes
                ],
            }
        )
        for d in drafts
    )
    _check_unique([e.id for e in entities], "엔티티")
    _check_unique([a.id for e in entities for a in e.attributes], "속성")
    return entities


def _stable_id(prefix: str, *parts: str) -> str:
    """실행이 달라도 같은 값이 나오는 ID. 한글 조합 방식 차이는 NFC로 맞춘다."""
    key = "\x1f".join(unicodedata.normalize("NFC", p) for p in parts)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:_ID_HEX_LENGTH]
    return f"{prefix}-{digest}"


def _check_unique(ids: Sequence[str], kind: str) -> None:
    """서로 다른 이름이 같은 ID가 되면 덮어쓰지 않고 멈춘다."""
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ValueError(f"A03: {kind} ID가 충돌합니다: {', '.join(duplicated)}")
