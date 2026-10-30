"""TC-A03: A03 엔티티·속성·CRUD 설계 노드. 실제 LLM 없이 stub 응답으로 검증한다.

예시의 requirements·functions는 A02 예시에서 가져와 두 단계가 같은 사례로 이어지는지 본다.
"""

import copy
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from specton.config import Settings
from specton.contracts import Crud, DesignState, Function, Requirement
from specton.contracts.state import find_trace_issues
from specton.llm.errors import LLMContractError, LLMRefusalError
from specton.llm.stub import refusal, reply, stub_client
from specton.nodes import a03_entities
from specton.nodes.a02_functions import A02Output
from specton.nodes.a03_entities import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    A03Output,
    A03Result,
    PackTerm,
    _checked_against,
    input_data,
    load_pack_context,
    run,
)
from specton.nodes.common import assign_ids, unwrap_data
from specton.packs.build import DEFAULT_ROOT
from specton.packs.examples import load_examples

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS = REPO_ROOT / DEFAULT_ROOT


def _yaml(relative: str) -> Any:
    return yaml.safe_load((PACKS / relative).read_text(encoding="utf-8"))


def _reasons(pack: dict[str, Any]) -> dict[str, list[Crud]]:
    return {r: [Crud(op) for op in ops] for r, ops in pack["crud_exemption_reasons"].items()}


def _a02_state(pack: str = "inventory") -> DesignState:
    """A02 예시의 입력·출력으로 만든 상태 (A02가 코드로 ID를 붙인 뒤의 모양)."""
    [example] = _yaml(f"{pack}/examples/A02.yaml")["examples"]
    requirements = tuple(
        Requirement(
            id=r["id"],
            source_ref={"kind": "csv", "row": n + 2},
            text=r["text"],
            original_text=r["text"],
            type=r["type"],
            nfr_category=r["nfr_category"],
            analysis_version=1,
        )
        for n, r in enumerate(example["input"]["requirements"])
    )
    drafts = A02Output.model_validate(example["output"]).functions
    functions = tuple(
        Function.model_validate({**d.model_dump(), "id": i})
        for d, i in zip(drafts, assign_ids("FUNC", len(drafts)), strict=True)
    )
    return DesignState(run_id="run-1", requirements=requirements, functions=functions)


def _example_terms(names: list[str]) -> list[PackTerm]:
    """예시 입력에 쓴 용어를 실제 팩에서 읽어 온다."""
    by_term = {t.term: t for t in load_pack_context("inventory").terms}
    return [by_term[n] for n in names]


def test_input_data_has_requirements_functions_and_pack() -> None:
    state = _a02_state()

    data = input_data(state, terms=[], exemption_reasons={"soft_delete": [Crud.DELETE]})

    assert set(data) == {"requirements", "functions", "pack"}
    assert [r["id"] for r in data["requirements"]] == ["REQ-01", "REQ-02", "REQ-03"]
    assert set(data["requirements"][0]) == {"id", "type", "nfr_category", "text"}
    # 우선순위·entity_ops·실행 정보는 LLM에 보여 주지 않는다
    assert data["functions"] == [
        {
            "id": "FUNC-01",
            "name": state.functions[0].name,
            "description": state.functions[0].description,
            "req_ids": ["REQ-01", "REQ-02", "REQ-03"],
        }
    ]
    assert data["pack"] == {"terms": [], "crud_exemption_reasons": {"soft_delete": ["D"]}}


def test_pack_term_drops_unset_fields_and_keeps_numeric_precision() -> None:
    state = _a02_state()
    terms = [
        PackTerm(term="거래수량", data_type="numeric", precision=10, scale=3),
        PackTerm(term="거래일시", data_type="timestamp"),
    ]

    data = input_data(state, terms=terms, exemption_reasons={})

    assert data["pack"]["terms"] == [
        {"term": "거래수량", "data_type": "numeric", "precision": 10, "scale": 3},
        {"term": "거래일시", "data_type": "timestamp"},
    ]


def test_inventory_example_loads_as_a03_output() -> None:
    examples = load_examples("inventory", "A03", A03Output)

    assert examples
    for example in examples:
        assert example.output.entities
        assert example.output.entity_ops


def test_inventory_example_input_is_what_input_data_builds() -> None:
    [example] = load_examples("inventory", "A03", A03Output)
    pack = example.input["pack"]
    terms = _example_terms([t["term"] for t in pack["terms"]])

    built = input_data(_a02_state(), terms=terms, exemption_reasons=_reasons(pack))

    assert example.input == built


def test_inventory_example_output_refers_only_to_its_input() -> None:
    [example] = load_examples("inventory", "A03", A03Output)
    function_ids = {f["id"] for f in example.input["functions"]}
    req_ids = {r["id"] for r in example.input["requirements"]}
    terms = {t["term"] for t in example.input["pack"]["terms"]}
    reasons = set(example.input["pack"]["crud_exemption_reasons"])
    entities = example.output.entities
    names = [e.name for e in entities]

    assert len(set(names)) == len(names)
    for entity in entities:
        assert set(entity.req_ids) <= req_ids
        assert {x.reason for x in entity.crud_exemptions} <= reasons
        attribute_names = [a.name for a in entity.attributes]
        assert len(set(attribute_names)) == len(attribute_names)
        assert set(attribute_names) <= terms
        assert all(set(a.req_ids) <= req_ids for a in entity.attributes)
    for op in example.output.entity_ops:
        assert op.function_id in function_ids
        assert op.entity_name in names
    # 면제한 조작은 entity_ops에 없어야 한다
    for entity in entities:
        exempt = {x.operation for x in entity.crud_exemptions}
        done = {
            c
            for op in example.output.entity_ops
            if op.entity_name == entity.name
            for c in op.operations
        }
        assert not exempt & done


def test_maintenance_example_input_is_what_input_data_builds() -> None:
    [example] = load_examples("maintenance", "A03", A03Output)
    pack = example.input["pack"]
    by_term = {t.term: t for t in load_pack_context("maintenance").terms}
    terms = [by_term[t["term"]] for t in pack["terms"]]

    built = input_data(_a02_state("maintenance"), terms=terms, exemption_reasons=_reasons(pack))

    assert example.input == built


def test_maintenance_example_passes_the_checks_for_its_own_input() -> None:
    [example] = load_examples("maintenance", "A03", A03Output)
    pack = example.input["pack"]
    checked = _checked_against(
        {f["id"] for f in example.input["functions"]},
        {r["id"] for r in example.input["requirements"]},
        [PackTerm.model_validate(t) for t in pack["terms"]],
        _reasons(pack),
    )

    checked.model_validate(example.output.model_dump(mode="json"))
    # 일반 사용자의 삭제 금지는 권한 요구다. 면제로 옮기지 않고 삭제 조작도 지어내지 않는다.
    assert not [e.name for e in example.output.entities if e.crud_exemptions]
    assert all(Crud.DELETE not in op.operations for op in example.output.entity_ops)


# 출력 검증: 검사는 모두 코드가 한다. 어기면 공통 client가 재요청한다.


def _checked() -> type[A03Output]:
    [example] = load_examples("inventory", "A03", A03Output)
    terms = [PackTerm.model_validate(t) for t in example.input["pack"]["terms"]]
    return _checked_against(
        {f["id"] for f in example.input["functions"]},
        {r["id"] for r in example.input["requirements"]},
        terms,
        _reasons(example.input["pack"]),
    )


def _output() -> dict[str, Any]:
    [example] = load_examples("inventory", "A03", A03Output)
    return copy.deepcopy(example.output.model_dump(mode="json"))


def test_example_passes_the_checks_for_its_own_input() -> None:
    _checked().model_validate(_output())


def test_prompt_version_is_fixed() -> None:
    assert PROMPT_VERSION == "a03-v1"
    assert SYSTEM_PROMPT.strip()


@pytest.mark.parametrize(
    "fields",
    [
        {"data_type": "varchar"},
        {"data_type": "integer", "length": 4},
        {"data_type": "numeric", "precision": 3, "scale": 4},
        {"data_type": "varchar", "length": 10, "precision": 5},
    ],
)
def test_pack_term_rejects_combinations_the_contract_rejects(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PackTerm.model_validate({"term": "x", **fields})


def _entity_op(data: dict[str, Any], **changes: Any) -> None:
    data["entity_ops"][0] |= changes


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: _entity_op(d, function_id="FUNC-99"), "입력에 없는 기능"),
        (lambda d: d["entities"][0].update(req_ids=["REQ-99"]), "입력에 없는 요구사항"),
        (
            lambda d: d["entities"][0]["attributes"][0].update(req_ids=["REQ-99"]),
            "입력에 없는 요구사항",
        ),
        (
            lambda d: d["entities"][0]["crud_exemptions"][0].update(reason="made_up"),
            "허용되지 않는 면제 사유",
        ),
        (
            lambda d: (
                d["entities"][0]["crud_exemptions"][0].update(operation="C"),
                d["entity_ops"][0].update(operations=["R", "U"]),
            ),
            r"사유가 면제할 수 없는 조작입니다: 창고\.C\(soft_delete\)",
        ),
        (
            lambda d: d["entities"][0]["attributes"][0].update(length=11),
            "팩 용어와 타입·길이가 다릅니다",
        ),
        (
            lambda d: d["entities"][0]["attributes"][0].update(data_type="text", length=None),
            "팩 용어와 타입·길이가 다릅니다",
        ),
    ],
)
def test_input_dependent_violation_is_rejected(mutate: Any, message: str) -> None:
    data = _output()
    mutate(data)

    with pytest.raises(ValidationError, match=message):
        _checked().model_validate(data)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["entities"][1].update(name="창고"), "엔티티 이름이 중복됩니다: 창고"),
        (
            lambda d: d["entities"][0]["attributes"].append(d["entities"][0]["attributes"][0]),
            "속성 이름이 중복됩니다",
        ),
        (lambda d: _entity_op(d, entity_name="없는엔티티"), "출력에 없는 엔티티"),
        (lambda d: d["entity_ops"].append(dict(d["entity_ops"][0])), "쌍이 중복됩니다"),
        (lambda d: _entity_op(d, operations=["C", "C"]), "operations에 중복"),
        (lambda d: _entity_op(d, operations=["C", "R", "U", "D"]), "면제한 조작이 entity_ops에 있"),
    ],
)
def test_output_violation_is_rejected_without_input(mutate: Any, message: str) -> None:
    data = _output()
    mutate(data)

    with pytest.raises(ValidationError, match=message):
        A03Output.model_validate(data)


def test_unknown_attribute_outside_the_pack_is_allowed() -> None:
    data = _output()
    data["entities"][0]["attributes"].append(
        {"name": "비고", "data_type": "text", "req_ids": ["REQ-01"]}
    )

    _checked().model_validate(data)


def test_entity_does_not_need_all_four_operations() -> None:
    data = _output()
    data["entity_ops"] = []
    data["entities"][0]["crud_exemptions"] = []

    _checked().model_validate(data)


@pytest.mark.parametrize("field", ["id", "foreign_key"])
def test_ids_and_fk_fields_are_not_accepted(field: str) -> None:
    data = _output()
    data["entities"][0]["attributes"][0][field] = "X"

    with pytest.raises(ValidationError, match="Extra inputs"):
        A03Output.model_validate(data)


def test_reason_may_exempt_every_operation_it_lists() -> None:
    data = _output()
    data["entities"][0]["crud_exemptions"] = [
        {"operation": "U", "reason": "immutable_ledger"},
        {"operation": "D", "reason": "immutable_ledger"},
    ]
    data["entity_ops"][0]["operations"] = ["C", "R"]

    _checked().model_validate(data)


def test_example_exemption_reasons_match_rules_yaml() -> None:
    [example] = load_examples("inventory", "A03", A03Output)

    assert example.input["pack"]["crud_exemption_reasons"] == {
        reason: [op for op in ops]
        for reason, ops in _yaml("common/rules.yaml")["crud_exemption_reasons"].items()
    }


# 팩 읽기


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
def test_pack_context_loads_every_term_and_the_exemption_table(pack: str) -> None:
    context = load_pack_context(pack)

    assert context.terms
    assert context.exemption_reasons == {
        reason: tuple(Crud(op) for op in ops)
        for reason, ops in _yaml("common/rules.yaml")["crud_exemption_reasons"].items()
    }


def test_pack_context_turns_domains_into_contract_types() -> None:
    by_term = {t.term: t for t in load_pack_context("inventory").terms}

    assert (by_term["창고코드"].data_type, by_term["창고코드"].length) == ("varchar", 10)
    # numeric의 길이는 precision으로, 시각 타입의 precision은 비운다
    quantity = by_term["거래수량"]
    assert (quantity.data_type, quantity.precision, quantity.scale) == ("numeric", 10, 3)
    assert quantity.length is None
    assert (by_term["거래일시"].data_type, by_term["거래일시"].precision) == ("timestamp", None)


# run: 정상 응답과 ID 부여


def _entity_id(name: str, pack: str = "inventory") -> str:
    return a03_entities._stable_id("ENT", pack, name)


def _settings() -> Settings:
    return Settings(_env_file=None)


def _example_output() -> A03Output:
    [example] = load_examples("inventory", "A03", A03Output)
    return example.output


def _raw(data: dict[str, Any]) -> str:
    """출력 모델을 거치지 않은 LLM 응답. 검증 위반을 재현할 때 쓴다."""
    return json.dumps(data, ensure_ascii=False)


def test_assigns_ids_and_fills_entity_ops_by_function() -> None:
    client, transport = stub_client(reply(_example_output()))

    result = run(client, _a02_state(), _settings(), pack="inventory")

    entities = result.output.entities
    assert [e.id for e in entities] == [_entity_id("창고"), _entity_id("품목")]
    assert all(re.fullmatch(r"ENT-[0-9a-f]{16}", e.id) for e in entities)
    assert {e.pack for e in entities} == {"inventory"}
    attribute_ids = [a.id for e in entities for a in e.attributes]
    assert all(re.fullmatch(r"ATTR-[0-9a-f]{16}", i) for i in attribute_ids)
    # 속성 ID는 엔티티를 넘어 겹치지 않는다 (두 엔티티 모두 사용여부가 있다)
    assert len(set(attribute_ids)) == len(attribute_ids) == 8
    [function] = result.output.functions
    assert [(op.entity_id, [c.value for c in op.operations]) for op in function.entity_ops] == [
        (_entity_id("창고"), ["C", "R", "U"]),
        (_entity_id("품목"), ["C", "R", "U"]),
    ]
    assert len(transport.sent) == 1
    assert [c.outcome for c in result.calls] == ["ok"]


def test_function_fields_other_than_entity_ops_are_kept() -> None:
    state = _a02_state()
    client, _ = stub_client(reply(_example_output()))

    [function] = run(client, state, _settings(), pack="inventory").output.functions

    before = state.functions[0]
    assert function.model_dump(exclude={"entity_ops"}) == before.model_dump(exclude={"entity_ops"})


def test_result_has_no_trace_issues() -> None:
    state = _a02_state()
    client, _ = stub_client(reply(_example_output()))

    result = run(client, state, _settings(), pack="inventory").output

    assert (
        find_trace_issues(state.evolve(entities=result.entities, functions=result.functions)) == []
    )


def test_request_uses_design_model_prompt_version_few_shot_and_input() -> None:
    settings = _settings()
    state = _a02_state()
    client, transport = stub_client(reply(_example_output()))

    run(client, state, settings, pack="inventory")

    (request,) = transport.sent
    assert (request.stage, request.prompt_version, request.model) == (
        "A03",
        PROMPT_VERSION,
        settings.design_model,
    )
    assert [m.role for m in request.messages] == ["system", "user", "assistant", "user"]
    context = load_pack_context("inventory")
    expected = input_data(state, terms=context.terms, exemption_reasons=context.exemption_reasons)
    assert json.loads(unwrap_data(request.messages[-1].content)) == expected


def test_operations_of_functions_sharing_an_entity_do_not_mix() -> None:
    state = _a02_state()
    second = state.functions[0].evolve(id="FUNC-02", name="창고 조회")
    state = state.evolve(functions=(*state.functions, second))
    data = _example_output().model_dump(mode="json")
    data["entity_ops"].append(
        {"function_id": "FUNC-02", "entity_name": "창고", "operations": ["R"]}
    )
    client, _ = stub_client(reply(_raw(data)))

    first, other = run(client, state, _settings(), pack="inventory").output.functions

    assert len(first.entity_ops) == 2
    assert [(op.entity_id, [c.value for c in op.operations]) for op in other.entity_ops] == [
        (_entity_id("창고"), ["R"])
    ]


def test_rerun_replaces_entity_ops_instead_of_accumulating() -> None:
    state = _a02_state()
    stale = state.functions[0].evolve(entity_ops=({"entity_id": "ENT-99", "operations": ["C"]},))
    other = stale.evolve(id="FUNC-02", name="다른 기능")
    client, _ = stub_client(reply(_example_output()))

    first, second = run(
        client, state.evolve(functions=(stale, other)), _settings(), pack="inventory"
    ).output.functions

    assert [op.entity_id for op in first.entity_ops] == [_entity_id("창고"), _entity_id("품목")]
    assert second.entity_ops == ()


# run: 계약 오류는 재요청, 거절은 그대로, 빈 입력은 호출 전 중단


def test_unknown_function_id_is_sent_back_for_retry() -> None:
    data = _example_output().model_dump(mode="json")
    data["entity_ops"][0]["function_id"] = "FUNC-99"
    client, transport = stub_client(reply(_raw(data)), reply(_example_output()))

    result = run(client, _a02_state(), _settings(), pack="inventory")

    assert len(transport.sent) == 2
    assert "FUNC-99" in transport.sent[1].messages[-1].content
    assert len(result.output.entities) == 2


def test_duplicate_entity_names_that_persist_fail_the_node() -> None:
    data = _example_output().model_dump(mode="json")
    data["entities"][1]["name"] = data["entities"][0]["name"]
    bad = reply(_raw(data))
    client, transport = stub_client(bad, bad, bad)

    with pytest.raises(LLMContractError, match="엔티티 이름이 중복됩니다"):
        run(client, _a02_state(), _settings(), pack="inventory")

    assert len(transport.sent) == 3


def test_exemption_with_wrong_operation_is_sent_back_for_retry() -> None:
    data = _example_output().model_dump(mode="json")
    data["entities"][0]["crud_exemptions"] = [{"operation": "C", "reason": "soft_delete"}]
    data["entity_ops"][0]["operations"] = ["R", "U"]
    client, transport = stub_client(reply(_raw(data)), reply(_example_output()))

    run(client, _a02_state(), _settings(), pack="inventory")

    assert len(transport.sent) == 2
    assert "면제할 수 없는 조작" in transport.sent[1].messages[-1].content


def test_malformed_reply_is_retried() -> None:
    client, transport = stub_client(reply("{}"), reply(_example_output()))

    run(client, _a02_state(), _settings(), pack="inventory")

    assert len(transport.sent) == 2


def test_refusal_is_raised_without_retry() -> None:
    client, transport = stub_client(refusal())

    with pytest.raises(LLMRefusalError):
        run(client, _a02_state(), _settings(), pack="inventory")

    assert len(transport.sent) == 1


@pytest.mark.parametrize(
    ("field", "message"),
    [("requirements", "요구사항이 없습니다"), ("functions", "기능이 없습니다")],
)
def test_empty_input_stops_before_calling_the_model(field: str, message: str) -> None:
    client, transport = stub_client()

    with pytest.raises(ValueError, match=message):
        run(client, _a02_state().evolve(**{field: ()}), _settings(), pack="inventory")

    assert not transport.sent


# ID: 팩·이름으로 계산해 재실행·삭제 후에도 같은 이름은 같은 ID, 다른 이름은 다른 ID


def _ids(
    data: dict[str, Any], state: DesignState
) -> tuple[dict[str, str], dict[tuple[str, str], str], A03Result]:
    client, _ = stub_client(reply(_raw(data)))
    result = run(client, state, _settings(), pack="inventory").output
    entities = {e.name: e.id for e in result.entities}
    attributes = {(e.name, a.name): a.id for e in result.entities for a in e.attributes}
    return entities, attributes, result


def _next(state: DesignState, result: A03Result) -> DesignState:
    return state.evolve(entities=result.entities, functions=result.functions)


def _partner() -> dict[str, Any]:
    return {
        "name": "거래처",
        "description": "거래 상대",
        "req_ids": ["REQ-01"],
        "attributes": [{"name": "거래처명", "data_type": "text", "req_ids": ["REQ-01"]}],
    }


def _without(data: dict[str, Any], name: str) -> dict[str, Any]:
    data = copy.deepcopy(data)
    data["entities"] = [e for e in data["entities"] if e["name"] != name]
    data["entity_ops"] = [op for op in data["entity_ops"] if op["entity_name"] != name]
    return data


def test_ids_are_fixed_values_of_pack_and_name() -> None:
    """알고리즘이 바뀌면 저장된 참조가 끊기므로 값을 고정해 둔다."""
    assert _entity_id("창고") == "ENT-98727dcf83e8b2b7"
    assert a03_entities._stable_id("ATTR", "inventory", "창고", "창고코드") == (
        "ATTR-6be8c07817773f78"
    )
    assert _entity_id("창고") != _entity_id("창고", pack="maintenance")
    assert a03_entities._stable_id("ATTR", "inventory", "창고", "사용여부") != (
        a03_entities._stable_id("ATTR", "inventory", "품목", "사용여부")
    )
    # 한글 조합 방식(NFC·NFD)이 달라도 같은 ID
    assert _entity_id(unicodedata.normalize("NFD", "창고")) == _entity_id("창고")


def test_rerun_keeps_ids_when_entities_and_attributes_are_reordered() -> None:
    original = _example_output().model_dump(mode="json")
    first, first_attributes, result = _ids(original, _a02_state())
    reordered = copy.deepcopy(original)
    reordered["entities"].reverse()
    for entity in reordered["entities"]:
        entity["attributes"].reverse()

    second, second_attributes, _ = _ids(reordered, _next(_a02_state(), result))

    assert second == first
    assert second_attributes == first_attributes


def test_object_added_after_a_deletion_does_not_get_the_deleted_id() -> None:
    """생성 → 다음 실행에서 삭제 → 그다음 실행에서 다른 객체 추가 (3회 실행)."""
    original = _example_output().model_dump(mode="json")
    first, first_attributes, result = _ids(original, _a02_state())
    deleted = _without(original, "품목")
    second, _, result = _ids(deleted, _next(_a02_state(), result))
    added = copy.deepcopy(deleted)
    added["entities"].append(_partner())

    third, third_attributes, _ = _ids(added, _next(_a02_state(), result))

    assert set(second) == {"창고"}
    assert third["창고"] == first["창고"]
    assert third["거래처"] not in first.values()
    assert third_attributes[("거래처", "거래처명")] not in first_attributes.values()


def test_readding_the_same_name_brings_back_the_same_id() -> None:
    original = _example_output().model_dump(mode="json")
    first, first_attributes, result = _ids(original, _a02_state())
    _, _, result = _ids(_without(original, "품목"), _next(_a02_state(), result))

    third, third_attributes, _ = _ids(original, _next(_a02_state(), result))

    assert third == first
    assert third_attributes == first_attributes


def test_renamed_entity_is_treated_as_a_new_object() -> None:
    original = _example_output().model_dump(mode="json")
    first, _, result = _ids(original, _a02_state())
    renamed = copy.deepcopy(original)
    renamed["entities"][0]["name"] = "보관창고"
    renamed["entity_ops"][0]["entity_name"] = "보관창고"

    second, _, _ = _ids(renamed, _next(_a02_state(), result))

    assert second["보관창고"] != first["창고"]
    assert second["품목"] == first["품목"]


def test_id_collision_stops_instead_of_overwriting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(a03_entities, "_stable_id", lambda prefix, *parts: f"{prefix}-same")
    client, _ = stub_client(reply(_example_output()))

    with pytest.raises(ValueError, match="엔티티 ID가 충돌합니다: ENT-same"):
        run(client, _a02_state(), _settings(), pack="inventory")
