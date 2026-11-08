"""RULE-07: SQL 검사 문제를 원래 설계 대상에 연결한다."""

import re

import pytest

from specton.codegen.ddl import generate_ddl
from specton.codegen.model import Column, ForeignKey, NormalizedModel, Table
from specton.contracts import (
    DesignState,
    Entity,
    Relationship,
    SqlValidation,
    StepStatus,
    ValidationStepName,
)
from specton.contracts.design import Attribute
from specton.contracts.findings import Severity
from specton.review.ddl_findings import ddl_validation_findings
from specton.validate.allowed_sql import build_result, check_allowed_sql, issue, step
from specton.validate.sandbox import _statement_texts


def _design() -> DesignState:
    a = Attribute(
        id="ATTR-1",
        name="warehouse",
        data_type="varchar",
        length=10,
        is_key=True,
        nullable=False,
        req_ids=("REQ-01",),
    )
    entities = tuple(
        Entity(
            id=f"ENT-{i}",
            pack="inventory",
            name=f"창고{i}",
            description="warehouse",
            attributes=(a,),
            req_ids=("REQ-01",),
        )
        for i in (1, 2)
    )
    rel = Relationship(
        id="REL-1",
        parent="ENT-1",
        child="ENT-2",
        cardinality="1:N",
        optional=True,
        rationale="warehouse relation",
        req_ids=("REQ-01",),
    )
    tables = tuple(
        Table(
            id=f"T{i}",
            name=f"창고{i}",
            physical_name=f"table_{i}",
            columns=(),
            primary_key=(),
            unique_keys=(),
            req_ids=("REQ-01",),
            entity_id=f"ENT-{i}",
        )
        for i in (2, 1)
    )
    fk = ForeignKey(
        id="FK-1",
        relationship_id="REL-1",
        table_id="T2",
        columns=(),
        parent_table_id="T1",
        parent_columns=(),
        req_ids=("REQ-01",),
    )
    model = NormalizedModel(
        pack="inventory",
        pack_version="1",
        rules_version="1",
        lexicon_digest="abc",
        tables=tables,
        foreign_keys=(fk,),
    )
    return DesignState(run_id="run-1", entities=entities, relationships=(rel,), normalized=model)


def _failed(statement: int, sql: bytes = b'CREATE TABLE "table_1" (id integer);') -> SqlValidation:
    return build_result(
        sql,
        [
            step(ValidationStepName.PARSE, StepStatus.PASSED),
            step(ValidationStepName.ALLOWED_STATEMENTS, StepStatus.PASSED),
            step(
                ValidationStepName.EXECUTE,
                StepStatus.FAILED,
                issue("execution_error", "참조 오류", statement=statement, sqlstate="42P01"),
            ),
            step(ValidationStepName.ROLLBACK, StepStatus.PASSED),
            step(ValidationStepName.CLEANUP, StepStatus.PASSED),
        ],
    )


def test_execute_failure_targets_source_relationship() -> None:
    result = ddl_validation_findings(
        _design(), _failed(2), severities={"RULE-07": Severity.CRITICAL}
    )
    assert len(result) == 1
    finding = result[0]
    assert (finding.rule_code, finding.kind, finding.severity, finding.target_stage) == (
        "RULE-07",
        "execute:execution_error",
        Severity.CRITICAL,
        None,
    )
    assert [(t.kind, t.id) for t in finding.targets] == [("relationship", "REL-1")]
    assert finding.evidence[0].quote == "문장 3: 참조 오류"


def test_create_failure_targets_original_entity_in_id_order() -> None:
    findings = ddl_validation_findings(
        _design(), _failed(0), severities={"RULE-07": Severity.CRITICAL}
    )
    assert [(t.kind, t.id) for t in findings[0].targets] == [("entity", "ENT-1")]


def test_unknown_statement_is_not_assigned_to_a_random_target() -> None:
    with pytest.raises(ValueError, match="문장 번호"):
        ddl_validation_findings(_design(), _failed(4), severities={"RULE-07": Severity.CRITICAL})


def test_unverified_is_blocked_by_graph_without_fake_sql_defect() -> None:
    result = check_allowed_sql(b'CREATE TABLE "a" (id integer PRIMARY KEY);')
    assert result.status == "unverified"
    assert ddl_validation_findings(_design(), result, severities={}) == ()


def test_parse_failure_keeps_all_known_sources() -> None:
    result = check_allowed_sql(b"CREATE TABLE (")
    findings = ddl_validation_findings(_design(), result, severities={"RULE-07": Severity.CRITICAL})
    assert [(t.kind, t.id) for t in findings[0].targets] == [
        ("entity", "ENT-1"),
        ("entity", "ENT-2"),
        ("relationship", "REL-1"),
    ]
    # 문장 번호가 없는 문제에는 「문장 N:」을 붙이지 않는다.
    assert not findings[0].evidence[0].quote.startswith("문장 ")


def _key(col_id: str, physical: str) -> Column:
    return Column(
        id=col_id,
        name=physical,
        physical_name=physical,
        data_type="varchar",
        length=10,
        precision=None,
        scale=None,
        time_precision=None,
        domain=None,
        nullable=False,
        req_ids=("REQ-01",),
    )


def _generated_design() -> DesignState:
    """실제 생성기로 SQL을 만들 수 있는 모델. 표·FK는 ID 순서와 다르게 넣는다."""
    base = _design()
    entities = tuple(
        Entity(
            id=f"ENT-{i}",
            pack="inventory",
            name=f"창고{i}",
            description="warehouse",
            attributes=base.entities[0].attributes,
            req_ids=("REQ-01",),
        )
        for i in (1, 2, 3)
    )
    relationships = tuple(
        Relationship(
            id=rel_id,
            parent="ENT-1",
            child=child,
            cardinality="1:N",
            optional=True,
            rationale="warehouse relation",
            req_ids=("REQ-01",),
        )
        for rel_id, child in (("REL-2", "ENT-3"), ("REL-1", "ENT-2"))
    )

    def table(i: int, *extra: Column) -> Table:
        return Table(
            id=f"T{i}",
            name=f"창고{i}",
            physical_name=f"table_{i}",
            columns=(_key(f"C{i}", f"key_{i}"), *extra),
            primary_key=(f"C{i}",),
            unique_keys=(),
            req_ids=("REQ-01",),
            entity_id=f"ENT-{i}",
        )

    tables = (table(3, _key("C31", "key_1")), table(1), table(2, _key("C21", "key_1")))
    fks = tuple(
        ForeignKey(
            id=fk_id,
            relationship_id=rel_id,
            table_id=child,
            columns=(col,),
            parent_table_id="T1",
            parent_columns=("C1",),
            req_ids=("REQ-01",),
        )
        for fk_id, rel_id, child, col in (
            ("FK-2", "REL-2", "T3", "C31"),
            ("FK-1", "REL-1", "T2", "C21"),
        )
    )
    model = NormalizedModel(
        pack="inventory",
        pack_version="1",
        rules_version="1",
        lexicon_digest="abc",
        tables=tables,
        foreign_keys=fks,
    )
    return DesignState(
        run_id="run-1", entities=entities, relationships=relationships, normalized=model
    )


def test_statement_numbers_follow_the_real_generator_output() -> None:
    # 변환기는 생성기 문장 순서를 따로 계산한다. 생성기 순서가 바뀌면 여기서 멈춘다.
    design = _generated_design()
    model = design.normalized
    assert model is not None
    sql = generate_ddl(model, max_bytes=63).sql.encode()
    texts = _statement_texts(sql.decode())
    # 기대 대상은 문장 글자(표 물리명)에서 읽는다. 이 시험의 FK는 자식 표마다 하나다.
    by_physical = {t.physical_name: t for t in model.tables}
    physical = {t.id: t.physical_name for t in model.tables}
    fk_by_child = {physical[fk.table_id]: fk for fk in model.foreign_keys}
    assert len(texts) == len(model.tables) + len(model.foreign_keys)
    for index, text in enumerate(texts):
        create = re.match(r'\s*CREATE TABLE "([^"]+)"', text)
        alter = re.match(r'\s*ALTER TABLE "([^"]+)" ADD FOREIGN KEY', text)
        if create:
            expected = ("entity", by_physical[create.group(1)].entity_id)
        else:
            assert alter, text
            expected = ("relationship", fk_by_child[alter.group(1)].relationship_id)
        [finding] = ddl_validation_findings(
            design, _failed(index, sql), severities={"RULE-07": Severity.CRITICAL}
        )
        assert [(t.kind, t.id) for t in finding.targets] == [expected], text


def _allowed_failed(*issues: tuple[int, str]) -> SqlValidation:
    return build_result(
        b'CREATE TABLE "table_1" (id integer);',
        [
            step(ValidationStepName.PARSE, StepStatus.PASSED),
            step(
                ValidationStepName.ALLOWED_STATEMENTS,
                StepStatus.FAILED,
                *(issue("not_allowed", message, statement=index) for index, message in issues),
            ),
            step(ValidationStepName.EXECUTE, StepStatus.NOT_RUN),
            step(ValidationStepName.ROLLBACK, StepStatus.NOT_RUN),
            step(ValidationStepName.CLEANUP, StepStatus.NOT_RUN),
        ],
    )


def test_same_fingerprint_becomes_one_finding_with_every_quote() -> None:
    # docs/04 「지적 확정 절차」: 지문이 같은 지적은 하나로 합치고 근거는 모두 남긴다.
    result = _allowed_failed((0, "문제 가"), (2, "문제 나"), (0, "문제 다"), (0, "문제 가"))
    findings = ddl_validation_findings(_design(), result, severities={"RULE-07": Severity.CRITICAL})

    assert [(f.id, [(t.kind, t.id) for t in f.targets]) for f in findings] == [
        ("RULE-07-0-1", [("entity", "ENT-1")]),
        ("RULE-07-0-2", [("relationship", "REL-1")]),
    ]
    assert [e.quote for e in findings[0].evidence] == ["문장 1: 문제 가", "문장 1: 문제 다"]
    assert [e.quote for e in findings[1].evidence] == ["문장 3: 문제 나"]
    assert len({f.fingerprint for f in findings}) == len(findings)
