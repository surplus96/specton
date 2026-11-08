"""RTM(요구사항 추적표): 원문 → 요구사항 → 기능 → 엔티티·관계 (#14, REQ-12, TC-F12, docs/10).

- 연결은 코드가 ID로만 조인한다. 요구사항 ID가 기능·엔티티·관계의 `req_ids`에 있으면 연결이다.
  LLM이나 이름 비슷함으로 링크를 추정해 메우지 않는다 (02 문서 「추정으로 메우지 않기」).
- 상태: 기능에 하나라도 연결되면 `연결`, 아니면 `미연결`.
- 추출 확인에서 뺀 원문은 `제외` 행(사유, 없으면 판정 이유), 원문 문장 없이 확인한 행은
  `확인(원문 없음)` 행(판정 이유)으로 남기고 둘 다 미연결로 세지 않는다 (ADR-0015).
- 같은 입력이면 같은 바이트다. xlsx의 작성 시각·zip 항목 시각을 고정한다.
- 이 모듈은 LLM client를 import하지 않는다 (CLAUDE.md, `codegen/` 규칙).
"""

import csv
import io
import re
import zipfile
from dataclasses import astuple, dataclass
from typing import Any

from openpyxl import Workbook  # type: ignore[import-untyped]
from openpyxl.styles import Alignment, Font  # type: ignore[import-untyped]

from specton.codegen.function_spec import DOCUMENT_INFO, document_info
from specton.contracts import DesignState, Requirement, SourceRequirement
from specton.contracts.base import ExtractionStatus, UserDecision

LINKED, UNLINKED, EXCLUDED, NO_TEXT = "연결", "미연결", "제외", "확인(원문 없음)"
COLUMNS = (
    "원문 ID", "원문 위치", "요구사항 ID", "상위 요구사항", "요구사항", "유형",
    "기능", "엔티티", "관계", "상태", "비고",
)  # fmt: skip
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")  # 스프레드시트가 수식으로 읽는 첫 글자
_CELL_LIMIT = 32_767  # 엑셀 한 칸의 최대 글자 수
_LONG_SHEET = "긴 글"
_FIXED_TIME = (2000, 1, 1, 0, 0, 0)  # xlsx zip 항목 시각 (같은 입력 → 같은 바이트)
_CORE_TIME = re.compile(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)")


@dataclass(frozen=True)
class RtmRow:
    source_id: str
    source_ref: str
    req_id: str
    parent_id: str
    text: str
    kind: str
    functions: str
    entities: str
    relationships: str
    status: str
    note: str


def build_rtm(design: DesignState) -> tuple[RtmRow, ...]:
    """원문 순서대로 행을 만든다. 한 원문을 나눈 요구사항은 그 원문 아래에 이어 둔다."""
    rows: list[RtmRow] = []
    placed: set[str] = set()
    for source in design.source_requirements:
        if source.analysable:
            for req in design.requirements:
                if req.id not in placed and _from(req, source):
                    rows.append(_requirement_row(design, req))
                    placed.add(req.id)
        else:
            rows.append(_source_row(source))
    # 원문 블록이 없는 예전 실행이나 원문과 이어지지 않는 요구사항도 빠뜨리지 않는다
    rows += [_requirement_row(design, r) for r in design.requirements if r.id not in placed]
    return tuple(rows)


def counts(rows: tuple[RtmRow, ...]) -> dict[str, int]:
    """상태별 건수. 제외·확인(원문 없음)은 미연결로 세지 않는다."""
    return {s: sum(r.status == s for r in rows) for s in (LINKED, UNLINKED, EXCLUDED, NO_TEXT)}


def render_rtm_csv(design: DesignState) -> bytes:
    """UTF-8(BOM) CSV. 엑셀에서 한글이 깨지지 않게 BOM을 붙인다. 줄 끝은 CRLF(RFC 4180).

    수식으로 읽힐 수 있는 칸(`=`·`+`·`-`·`@`·탭·CR로 시작)은 앞에 `'`를 붙인다 (#215 리뷰).
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    writer.writerows([_csv_safe(v) for v in astuple(r)] for r in build_rtm(design))
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def render_rtm_xlsx(design: DesignState) -> bytes:
    """시트 「RTM」(행)과 「문서 정보」(기능 명세서와 같은 문서 정보 + 상태별 건수).

    모든 글 칸은 수식이 아닌 문자열로 쓴다. 엑셀 한 칸 한도(32,767자)를 넘는 글은 자르지 않고
    「긴 글」 시트에 조각으로 나눠 모두 남기며, RTM 칸에는 그 위치를 적는다 (#215 리뷰).
    """
    rows = build_rtm(design)
    book = Workbook()
    sheet = book.active
    sheet.title = "RTM"
    sheet.append(COLUMNS)
    long_texts: list[tuple[str, int, str, int, str]] = []
    for line, row in enumerate(rows, start=2):
        for column, (name, value) in enumerate(zip(COLUMNS, astuple(row), strict=True), 1):
            if len(value) > _CELL_LIMIT:
                key = f"긴 글 {len(long_texts) + 1}"
                pieces = [value[i : i + _CELL_LIMIT] for i in range(0, len(value), _CELL_LIMIT)]
                long_texts += [(key, line, name, n, p) for n, p in enumerate(pieces, 1)]
                value = f"[「{_LONG_SHEET}」 시트 {key}, {len(value)}자]"
            _text_cell(sheet, line, column, value)
    if long_texts:
        extra = book.create_sheet(_LONG_SHEET)
        extra.append(("번호", "RTM 행", "칸", "조각", "내용"))
        for line, (key, at, name, n, piece) in enumerate(long_texts, start=2):
            for column, value in enumerate((key, at, name, n), 1):
                extra.cell(row=line, column=column, value=value)
            _text_cell(extra, line, 5, piece)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for line in sheet.iter_rows(min_row=2):
        for cell in line:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"
    info = book.create_sheet("문서 정보")
    values = document_info(design)
    info.append(("항목", "값"))
    for label, key in DOCUMENT_INFO:
        info.append((f"{label} ({key})", values[key]))
    for status, count in counts(rows).items():
        info.append((f"{status} 건수", count))
    book.properties.creator = "Specton"
    buffer = io.BytesIO()
    book.save(buffer)
    return _fixed(buffer.getvalue())


def _text_cell(sheet: Any, row: int, column: int, value: str) -> None:
    """수식(`=`로 시작)으로 해석하지 않도록 문자열 형식을 명시한다."""
    cell = sheet.cell(row=row, column=column, value=value)
    cell.data_type = "s"


def _csv_safe(value: str) -> str:
    return f"'{value}" if value.startswith(_FORMULA_STARTS) else value


def _from(req: Requirement, source: SourceRequirement) -> bool:
    return req.source_ref == source.source_ref and req.source_id == source.source_id


def _requirement_row(design: DesignState, req: Requirement) -> RtmRow:
    functions = [f"{f.id} {f.name}" for f in design.functions if req.id in f.req_ids]
    entities = [f"{e.id} {e.name}" for e in design.entities if req.id in e.req_ids]
    relationships = [r.id for r in design.relationships if req.id in r.req_ids]
    kind = req.type.value if req.nfr_category is None else f"NFR({req.nfr_category.value})"
    return RtmRow(
        source_id=req.source_id or "",
        source_ref=req.source_ref.display(),
        req_id=req.id,
        parent_id=req.parent_id or "",
        text=req.text,
        kind=kind,
        functions="; ".join(functions),
        entities="; ".join(entities),
        relationships="; ".join(relationships),
        status=LINKED if functions else UNLINKED,
        note="",
    )


def _source_row(source: SourceRequirement) -> RtmRow:
    if source.user_decision is UserDecision.EXCLUDED:
        status, note = EXCLUDED, source.excluded_reason or source.notice or ""
    elif source.extraction_status is ExtractionStatus.FAIL:
        raise ValueError(f"{source.block_id}: 제외하지 않은 fail 블록이 있습니다 (ADR-0015)")
    else:  # 원문 문장 없이 확인한 행
        status, note = NO_TEXT, source.notice or ""
    return RtmRow(
        source_id=source.source_id or "",
        source_ref=source.source_ref.display(),
        req_id="",
        parent_id="",
        text=source.source_text or "",
        kind="",
        functions="",
        entities="",
        relationships="",
        status=status,
        note=note,
    )


def _fixed(content: bytes) -> bytes:
    """zip 항목 시각과 문서 작성·수정 시각을 고정해 같은 입력이면 같은 바이트로 만든다."""
    source = zipfile.ZipFile(io.BytesIO(content))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "docProps/core.xml":
                data = _CORE_TIME.sub(rb"\g<1>2000-01-01T00:00:00Z\g<2>", data)
            info = zipfile.ZipInfo(item.filename, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, data)
    return output.getvalue()
