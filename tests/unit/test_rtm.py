"""#14: RTM(요구사항 추적표)·출력 manifest (REQ-12, TC-F12, docs/10, ADR-0015)."""

import csv
import io
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from specton.codegen.manifest import build_manifest, render_manifest
from specton.codegen.rtm import (
    COLUMNS,
    EXCLUDED,
    LINKED,
    NO_TEXT,
    UNLINKED,
    build_rtm,
    counts,
    render_rtm_csv,
    render_rtm_xlsx,
)
from specton.contracts import (
    DesignState,
    Entity,
    Function,
    Relationship,
    Requirement,
    SourceRequirement,
    VersionInfo,
)
from specton.model_hash import model_hash
from specton.rtm_node import create_rtm_artifacts, rtm_node

RUN_ID = "00000000-0000-4000-8000-000000000140"


def _ref(row: int) -> dict[str, object]:
    return {"file_format": "xlsx", "sheet": "요구사항", "row": row}


def _source(row: int, source_id: str, text: str | None, **extra: object) -> SourceRequirement:
    return SourceRequirement.model_validate({
        "document_id": "doc-1", "block_id": f"B-{row}", "source_id": source_id,
        "source_ref": _ref(row), "source_text": text, "extraction_status": "pass", **extra,
    })  # fmt: skip


def _req(req_id: str, row: int, source_id: str, text: str, **extra: object) -> Requirement:
    return Requirement.model_validate({
        "id": req_id, "source_id": source_id, "source_ref": _ref(row), "text": text,
        "draft_text": text, "type": "FR", "analysis_version": 1, **extra,
    })  # fmt: skip


def _entity(index: int, name: str, req_ids: list[str]) -> Entity:
    return Entity.model_validate({
        "id": f"ENT-{index:02}", "pack": "inventory", "name": name, "description": name,
        "req_ids": req_ids, "attributes": [{
            "id": f"ATTR-{index:02}", "name": f"{name}코드", "data_type": "varchar",
            "length": 10, "is_key": True, "nullable": False, "req_ids": req_ids,
        }],
    })  # fmt: skip


def _design(functions: tuple[Function, ...] | None = None) -> DesignState:
    sources = (
        _source(2, "SFR-001", "입고를 등록하고 조회한다"),
        _source(3, "SFR-002", "공지 화면", extraction_status="review", notice="표 밖 문단",
                user_decision="excluded", excluded_reason="안내 문단"),
        _source(4, "SFR-003", None, extraction_status="review", notice="원문 문장 칸이 비어 있음",
                user_decision="confirmed"),
        _source(5, "PER-001", "조회는 3초 안에 끝나야 한다"),
    )  # fmt: skip
    requirements = (
        _req("REQ-01", 2, "SFR-001", "입고를 등록한다"),
        _req("REQ-02", 2, "SFR-001", "입고를 조회한다", parent_id="REQ-01"),
        _req("REQ-03", 5, "PER-001", "조회는 3초 안에 끝나야 한다", type="NFR",
             nfr_category="performance"),
    )  # fmt: skip
    if functions is None:
        functions = (
            Function(id="FUNC-01", name="입고 등록", description="입고를 등록한다",
                     req_ids=("REQ-01",)),
            Function(id="FUNC-02", name="입고 조회", description="3초 안에 조회한다",
                     req_ids=("REQ-02", "REQ-03")),
        )  # fmt: skip
    return DesignState(
        run_id=RUN_ID,
        revision=1,
        versions=VersionInfo(
            document_hash="d" * 64,
            pack_id="inventory",
            pack_version="0.1.16",
            prompt_versions={"A02": "a02-v3", "A01": "a01-v2"},
        ),
        source_requirements=sources,
        requirements=requirements,
        functions=functions,
        entities=(_entity(1, "입고", ["REQ-01", "REQ-02"]), _entity(2, "창고", ["REQ-01"])),
        relationships=(
            Relationship(
                id="REL-01",
                parent="ENT-02",
                child="ENT-01",
                cardinality="1:N",
                optional=False,
                rationale="입고는 창고에 한다",
                req_ids=("REQ-01",),
            ),
        ),
    )


def test_rows_follow_the_sources_and_join_by_id() -> None:
    rows = build_rtm(_design())

    assert [(r.source_id, r.req_id, r.status) for r in rows] == [
        ("SFR-001", "REQ-01", LINKED),
        ("SFR-001", "REQ-02", LINKED),
        ("SFR-002", "", EXCLUDED),
        ("SFR-003", "", NO_TEXT),
        ("PER-001", "REQ-03", LINKED),
    ]
    first, split, excluded, no_text, nfr = rows
    assert (first.functions, first.entities, first.relationships, first.source_ref) == (
        "FUNC-01 입고 등록", "ENT-01 입고; ENT-02 창고", "REL-01", "요구사항!2행",
    )  # fmt: skip
    assert split.relationships == ""
    assert (split.parent_id, split.functions) == ("REQ-01", "FUNC-02 입고 조회")
    assert (excluded.note, excluded.text) == ("안내 문단", "공지 화면")
    assert (no_text.note, no_text.text) == ("원문 문장 칸이 비어 있음", "")
    assert (nfr.kind, nfr.entities) == ("NFR(performance)", "")


def test_removed_function_link_shows_unlinked_without_guessing() -> None:
    """TC-F12: 기능 연결 하나를 빼면 미연결이다. 이름이 비슷한 기능이 있어도 추정해 잇지 않는다."""
    design = _design()
    cut = design.functions[1].evolve(req_ids=("REQ-03",))  # REQ-02 연결 제거
    rows = build_rtm(design.evolve(functions=(design.functions[0], cut)))

    by_id = {r.req_id: r for r in rows if r.req_id}
    assert (by_id["REQ-02"].status, by_id["REQ-02"].functions) == (UNLINKED, "")
    assert by_id["REQ-02"].entities == "ENT-01 입고"  # 엔티티 연결은 그대로 보인다
    assert counts(rows) == {LINKED: 2, UNLINKED: 1, EXCLUDED: 1, NO_TEXT: 1}


def test_excluded_and_no_text_rows_are_not_counted_as_unlinked() -> None:
    assert counts(build_rtm(_design())) == {LINKED: 3, UNLINKED: 0, EXCLUDED: 1, NO_TEXT: 1}


def test_undecided_fail_block_is_rejected() -> None:
    design = _design()
    failed = _source(6, "SFR-009", "깨진 표", extraction_status="fail", notice="표를 읽지 못함")
    with pytest.raises(ValueError, match="fail 블록"):
        build_rtm(design.evolve(source_requirements=(*design.source_requirements, failed)))


def test_requirements_without_a_source_block_are_still_listed() -> None:
    """원문 블록이 없는 예전 실행에서도 요구사항을 빠뜨리지 않는다."""
    rows = build_rtm(_design().evolve(source_requirements=()))
    assert [r.req_id for r in rows] == ["REQ-01", "REQ-02", "REQ-03"]


def test_csv_has_bom_crlf_and_the_columns() -> None:
    content = render_rtm_csv(_design())

    assert content.startswith("﻿".encode())
    assert b"\r\n" in content
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline="")))
    assert tuple(rows[0]) == COLUMNS
    assert rows[3][COLUMNS.index("상태")] == EXCLUDED
    assert content == render_rtm_csv(_design())


def test_xlsx_is_readable_and_the_same_bytes_every_time() -> None:
    design = _design()
    content = render_rtm_xlsx(design)

    assert content == render_rtm_xlsx(design)
    book = load_workbook(io.BytesIO(content))
    assert book.sheetnames == ["RTM", "문서 정보"]
    sheet = book["RTM"]
    assert tuple(c.value for c in sheet[1]) == COLUMNS
    assert sheet.cell(row=2, column=COLUMNS.index("기능") + 1).value == "FUNC-01 입고 등록"
    info = {r[0].value: r[1].value for r in book["문서 정보"].iter_rows(min_row=2)}
    assert info["모델 해시 (model_hash)"] == model_hash(design)
    assert (info["미연결 건수"], info["제외 건수"]) == (0, 1)


def test_rtm_files_are_saved_as_two_drafts(tmp_path: Path) -> None:
    design = _design()

    output = rtm_node(tmp_path)({"design": design})  # type: ignore[typeddict-item]

    generated = output["generated_artifacts"]
    assert sorted(generated) == ["1:rtm:csv", "1:rtm:xlsx"]
    for item in generated.values():
        assert (item["ref"].kind, item["ref"].approved) == ("rtm", False)
        assert (tmp_path / item["storage_ref"]).is_file()
    assert create_rtm_artifacts(design, storage_dir=tmp_path) == sorted(
        generated.values(), key=lambda g: g["ref"].file_format, reverse=True
    )


def test_manifest_lists_versions_and_file_hashes(tmp_path: Path) -> None:
    design = _design()
    generated = create_rtm_artifacts(design, storage_dir=tmp_path)

    manifest = build_manifest(design, generated)

    assert manifest["run_id"] == RUN_ID
    assert (manifest["revision"], manifest["model_hash"]) == ("1", model_hash(design))
    assert (manifest["source_hash"], manifest["approved"]) == ("d" * 64, False)
    assert list(manifest["prompt_versions"]) == ["A01", "A02"]
    assert [(f["kind"], f["file_format"]) for f in manifest["files"]] == [
        ("rtm", "csv"), ("rtm", "xlsx"),
    ]  # fmt: skip
    assert json.loads(render_manifest(manifest)) == manifest
    assert render_manifest(manifest) == render_manifest(build_manifest(design, generated[::-1]))


def test_manifest_does_not_mix_revisions_models_or_drafts(tmp_path: Path) -> None:
    design = _design()
    draft = create_rtm_artifacts(design, storage_dir=tmp_path)
    later = create_rtm_artifacts(design.evolve(revision=2), storage_dir=tmp_path)
    approved = {**draft[0], "ref": draft[0]["ref"].evolve(approved=True)}

    with pytest.raises(ValueError, match="현재 모델"):
        build_manifest(design, [*draft, later[0]])
    with pytest.raises(ValueError, match="섞을 수 없습니다"):
        build_manifest(design, [approved, draft[1]])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="산출물이 없습니다"):
        build_manifest(design, [])
