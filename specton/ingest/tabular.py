"""엑셀·CSV 요구사항 표를 원문 한 건씩(`SourceRequirement`)으로 읽는다 (ADR-0003, docs/10).

- 요구사항 1건 = 1행이다 (docs/05). 단 ID 칸이 세로 병합된 행들은 1건이다(아래).
  행 번호는 파일에 보이는 번호(1부터, 머리글 포함)다.
- 머리글은 시트마다 위 20행 안에서 「요구사항 ID」와 「요구사항명 또는 상세 내용」이 함께 있는 행을
  찾는다. ID 칸이 없는 양식은 「요구사항명」과 「상세 내용」이 함께 있으면 읽고, 원문 위치로 잇는다.
  2단 머리글은 위아래 칸 이름을 합쳐 읽는다.
- 상세 내용 칸이 여럿이면(예: 「정의」·「세부 내용」) 왼쪽부터 줄바꿈으로 이어 원문 문장으로 쓴다.
  칸마다 글자는 원문 그대로다.
- 병합 칸은 왼쪽 위 값으로 채운다 (세로 병합된 구분 칸 등).
- ID 칸이 실제로 세로 병합된 행들은 요구사항 1건으로 묶는다. 묶인 행의 다른 칸 값은
  위에서부터 줄바꿈으로 잇는다.
- 수식은 실행하지 않고 엑셀에 저장된 결과값만 쓴다. 결과값이 없으면 `review`로 둔다.
- 행을 조용히 버리지 않는다. 원문 문장을 만들 수 없는 행은
  `ExtractionIssue`(확인 필요 1건)로 돌려준다.
"""

import csv
import io
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from openpyxl import load_workbook  # type: ignore[import-untyped]
from openpyxl.utils.exceptions import InvalidFileException  # type: ignore[import-untyped]
from openpyxl.worksheet.worksheet import Worksheet  # type: ignore[import-untyped]

from specton.contracts.base import ExtractionStatus, SourceRef
from specton.contracts.requirements import SourceRequirement

HEADER_SCAN_ROWS = 20
DEFAULT_COLUMN_MAP = Path(__file__).with_name("column_map.yaml")
# 머리글로 인정하는 기준 열 조합. 키 뜻은 column_map.yaml 머리 설명을 본다.
# source_id = 「요구사항 ID」(고객 원문 고유번호)
# name = 「요구사항명」(요구사항 제목·명칭, ID가 아님) / description = 「상세 내용」(요구사항 본문)
# 조합 하나라도 모두 있으면 머리글이다. ID가 없는 조합은 명칭과 내용이 둘 다 있어야 한다.
_REQUIRED_SETS = (("source_id", "name"), ("source_id", "description"), ("name", "description"))
_CSV_ENCODINGS = ("utf-8-sig", "cp949")
_CSV_DELIMITERS = ",;\t|"
_UNSUPPORTED_EXCEL = {
    ".xlsm": "매크로가 든 엑셀(.xlsm)",
    ".xls": "옛 엑셀(.xls)",
    ".xlsb": "바이너리 엑셀(.xlsb)",
}


class UnsupportedInput(ValueError):
    """읽지 않는 파일. 메시지는 사용자에게 그대로 보여 줄 문장이다."""


@dataclass(frozen=True)
class ExtractionIssue:
    """확인 필요 1건. 원문 한 건(`SourceRequirement`)으로 만들지 못한 자리를 위치와 함께 남긴다.

    화면에서는 「확인 필요」 목록의 한 건으로 보이고, 개수는 「확인 필요 3건」처럼 센다.
    실패(코드가 읽지 못함)도 확인 필요의 한 종류로 여기에 담는다.
    """

    source_ref: SourceRef  # 어디서: 엑셀 시트·행 / CSV 행 / 한글은 구역·문단·표 칸(#24)
    notice: str  # 화면 「확인 필요」에 보이는 문장. 사용자가 읽는다. 고객 원문은 넣지 않는다
    detail: str  # 화면 「상세 내용」에 보이는 단서. 개발자가 원인을 찾을 때도 쓴다


@dataclass(frozen=True)
class TabularResult:
    """표 형태 파일(엑셀·CSV) 한 개를 읽은 결과 묶음."""

    requirements: tuple[SourceRequirement, ...]  # 읽은 원문들 (1건 = 1행)
    issues: tuple[ExtractionIssue, ...] = ()  # 확인 필요 건 목록 (ExtractionIssue 여러 개)
    # 머리글을 찾지 못해 통째로 건너뛴 시트 이름 (표지·개정이력 등). 엑셀만 해당.
    # 건너뛰는 곳: read_excel 안 `if header is None: skipped.append(...)`
    skipped_sheets: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Header:
    last_row: int  # 머리글 마지막 행 (0부터)
    columns: dict[str, int]  # 기준 열 키 → 열 번호 (0부터). 같은 키가 여럿이면 가장 왼쪽 열
    labels: dict[int, str] = field(default_factory=dict)  # 열 번호 → 원문 머리글 이름
    description_cols: tuple[int, ...] = ()  # 상세 내용으로 읽는 열 전부 (왼쪽부터)


@dataclass(frozen=True)
class _Cell:
    value: str
    uncached_formula: bool = False
    # 세로로 2행 이상 병합된 칸이면 병합 범위의 (첫 행, 마지막 행), 0부터. 아니면 None
    vertical_merge: tuple[int, int] | None = None


def load_column_map(path: Path = DEFAULT_COLUMN_MAP) -> dict[str, tuple[str, ...]]:
    """이름 앞의 「=」는 그 이름과 똑같을 때만 맞춘다는 표시다 (끝부분 일치를 하지 않음)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        key: tuple(("=" + _norm(n[1:])) if n.startswith("=") else _norm(n) for n in names)
        for key, names in raw.items()
    }


def read_excel(
    path: Path, document_id: str, column_map: dict[str, tuple[str, ...]] | None = None
) -> TabularResult:
    """엑셀(.xlsx)의 모든 시트를 읽는다."""
    reason = _UNSUPPORTED_EXCEL.get(path.suffix.lower())
    if reason:
        raise UnsupportedInput(f"{reason}은 읽지 않습니다. .xlsx로 다시 저장해 올려 주세요.")
    columns = column_map or load_column_map()
    try:
        values_book = load_workbook(path, data_only=True)
        formula_book = load_workbook(path, data_only=False)
    except (InvalidFileException, KeyError, ValueError) as exc:
        # Strict OOXML 등 openpyxl이 읽지 못하는 형식
        raise UnsupportedInput(
            "엑셀 파일을 읽지 못했습니다. "
            "엑셀에서 「Excel 통합 문서(.xlsx)」로 다시 저장해 올려 주세요."
        ) from exc

    requirements: list[SourceRequirement] = []
    issues: list[ExtractionIssue] = []
    skipped: list[str] = []
    for sheet in values_book.worksheets:
        grid = _sheet_grid(sheet, formula_book[sheet.title])
        header = _find_header([[c.value for c in row] for row in grid], columns)
        if header is None:
            skipped.append(sheet.title)
            continue
        for index, row in _row_groups(grid, header):
            ref = SourceRef(file_format="xlsx", sheet=sheet.title, row=index + 1)
            built = _build_row(row, header, ref, document_id, f"xlsx:{sheet.title}:{index + 1}")
            if isinstance(built, ExtractionIssue):
                issues.append(built)
            elif built is not None:
                requirements.append(built)
    return TabularResult(_mark_duplicates(requirements), tuple(issues), tuple(skipped))


def read_csv(
    path: Path, document_id: str, column_map: dict[str, tuple[str, ...]] | None = None
) -> TabularResult:
    """CSV를 읽는다. 인코딩은 UTF-8, CP949 순서로, 구분자는 내용으로 고른다."""
    columns = column_map or load_column_map()
    text = _decode(path.read_bytes())
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=_CSV_DELIMITERS)
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    grid = [
        [_Cell(value.strip()) for value in row]
        for row in csv.reader(io.StringIO(text), delimiter=delimiter)
    ]
    header = _find_header([[c.value for c in row] for row in grid], columns)
    if header is None:
        raise UnsupportedInput(
            f"위 {HEADER_SCAN_ROWS}행 안에서 머리글을 찾지 못했습니다. "
            "「요구사항 ID」와 「요구사항명」 또는 「상세 내용」 칸이 있어야 합니다 "
            "(ID 칸이 없으면 「요구사항명」과 「상세 내용」)."
        )
    requirements: list[SourceRequirement] = []
    issues: list[ExtractionIssue] = []
    for index in range(header.last_row + 1, len(grid)):
        ref = SourceRef(file_format="csv", row=index + 1)
        built = _build_row(grid[index], header, ref, document_id, f"csv:{index + 1}")
        if isinstance(built, ExtractionIssue):
            issues.append(built)
        elif built is not None:
            requirements.append(built)
    return TabularResult(_mark_duplicates(requirements), tuple(issues))


def _decode(data: bytes) -> str:
    for encoding in _CSV_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnsupportedInput("CSV 인코딩을 알 수 없습니다. UTF-8 또는 CP949로 저장해 올려 주세요.")


def _norm(text: str) -> str:
    return "".join(text.split()).lower()


def _sheet_grid(values: Worksheet, formulas: Worksheet) -> list[list[_Cell]]:
    """시트를 문자열 격자로 바꾼다. 병합 칸은 왼쪽 위 값으로 채운다."""
    rows = values.max_row
    cols = values.max_column
    grid = [
        [_cell(values.cell(r, c).value, formulas.cell(r, c).value) for c in range(1, cols + 1)]
        for r in range(1, rows + 1)
    ]
    for merged in values.merged_cells.ranges:
        top = grid[merged.min_row - 1][merged.min_col - 1]
        if merged.max_row > merged.min_row:
            top = _Cell(top.value, top.uncached_formula, (merged.min_row - 1, merged.max_row - 1))
        for r in range(merged.min_row, merged.max_row + 1):
            for c in range(merged.min_col, merged.max_col + 1):
                grid[r - 1][c - 1] = top
    return grid


def _row_groups(grid: list[list[_Cell]], header: _Header) -> list[tuple[int, list[_Cell]]]:
    """머리글 아래 행을 요구사항 단위로 묶는다. ID 칸이 세로 병합된 행들은 1건으로 합친다.

    돌려주는 값: (첫 행 번호(0부터), 합친 행) 목록.
    """
    id_col = header.columns.get("source_id")
    groups: list[tuple[int, list[_Cell]]] = []
    index = header.last_row + 1
    while index < len(grid):
        row = grid[index]
        span = row[id_col].vertical_merge if id_col is not None and id_col < len(row) else None
        if span and span[0] == index and span[1] > index:
            last = min(span[1], len(grid) - 1)
            groups.append((index, _merge_rows(grid[index : last + 1])))
            index = last + 1
            continue
        groups.append((index, row))
        index += 1
    return groups


def _merge_rows(rows: list[list[_Cell]]) -> list[_Cell]:
    """여러 행을 한 행으로: 칸마다 서로 다른 값을 위에서부터 줄바꿈으로 잇는다."""
    width = max(len(r) for r in rows)
    merged = []
    for col in range(width):
        cells = [r[col] for r in rows if col < len(r)]
        values: list[str] = []
        for cell in cells:
            if cell.value and cell.value not in values:
                values.append(cell.value)
        merged.append(_Cell("\n".join(values), any(cell.uncached_formula for cell in cells)))
    return merged


def _cell(cached: object, raw: object) -> _Cell:
    is_formula = isinstance(raw, str) and raw.startswith("=")
    if cached is None:
        return _Cell("", uncached_formula=is_formula)
    return _Cell(str(cached).strip())


def _find_header(rows: list[list[str]], column_map: dict[str, tuple[str, ...]]) -> _Header | None:
    for top in range(min(HEADER_SCAN_ROWS, len(rows))):
        upper = rows[top]
        if len({v for v in upper if v}) < 2:
            continue  # 제목 줄처럼 값이 하나뿐인 행은 머리글이 아니다
        single = _match(upper, column_map)
        lower = rows[top + 1] if top + 1 < len(rows) else []
        combined = _combine(upper, lower) if lower else []
        joined = _match(combined, column_map) if combined else None
        if joined is not None and (single is None or _continues_header(upper, lower, single)):
            return _with_title_column(
                _Header(top + 1, joined, _labels(combined), _all_cols(combined, column_map))
            )
        if single is not None:
            return _with_title_column(
                _Header(top, single, _labels(upper), _all_cols(upper, column_map))
            )
    return None


def _with_title_column(header: _Header) -> _Header:
    """「요구사항」 칸은 본문으로 읽는다. 다른 본문 칸이 같이 있으면 「요구사항」 칸은 명칭이다
    (예: 「요구사항」 + 「요구사항 설명」)."""
    plain = [c for c in header.description_cols if _norm(header.labels.get(c, "")) == "요구사항"]
    if not plain or len(header.description_cols) < 2:
        return header
    columns = dict(header.columns)
    columns.setdefault("name", plain[0])
    rest = tuple(c for c in header.description_cols if c not in plain)
    if columns.get("description") in plain:
        columns["description"] = rest[0]
    return _Header(header.last_row, columns, header.labels, rest)


def _continues_header(upper: list[str], lower: list[str], single: dict[str, int]) -> bool:
    """아래 행이 2단 머리글의 둘째 줄인가: ID 칸이 위 칸과 같거나(세로 병합) 비어 있고,
    다른 칸 어딘가에 위와 다른 이름이 있다."""
    id_col = single.get("source_id")
    if id_col is not None:
        id_value = lower[id_col] if id_col < len(lower) else ""
        if id_value and id_value != upper[id_col]:
            return False
    return any(low and low != up for up, low in zip(upper, lower, strict=False))


def _combine(upper: list[str], lower: list[str]) -> list[str]:
    """2단 머리글: 위 칸 이름과 아래 칸 이름을 합친다. 아래가 비면 위 이름만 쓴다."""
    width = max(len(upper), len(lower))
    out = []
    for i in range(width):
        up = upper[i] if i < len(upper) else ""
        low = lower[i] if i < len(lower) else ""
        out.append(f"{up} {low}".strip() if low and low != up else up)
    return out


def _match(labels: list[str], column_map: dict[str, tuple[str, ...]]) -> dict[str, int] | None:
    found: dict[str, int] = {}
    for col, label in enumerate(labels):
        key = _label_key(label, column_map)
        if key is not None and key not in found:
            found[key] = col
    plain = [c for c in _all_cols(labels, column_map) if _norm(labels[c]) == "요구사항"]
    others = [c for c in _all_cols(labels, column_map) if c not in plain]
    if plain and others:  # 「요구사항」 + 다른 본문 칸 → 「요구사항」은 명칭
        found.setdefault("name", plain[0])
        found["description"] = others[0]
    if any(all(key in found for key in keys) for keys in _REQUIRED_SETS):
        return found
    return None


def _label_key(label: str, column_map: dict[str, tuple[str, ...]]) -> str | None:
    """머리글 이름 하나가 어느 기준 열 키인지. 없으면 None."""
    normalized = _norm(label)
    if not normalized:
        return None
    # 「소분류(기능설명)」처럼 괄호 안에 칸 이름이 있으면 괄호 안 글자도 맞춰 본다
    base, _, inner = normalized.partition("(")
    inner = inner.rstrip(")")
    for key, names in column_map.items():
        for name in names:
            if name.startswith("="):
                if normalized == name[1:]:
                    return key
            elif any(t and (t == name or t.endswith(name)) for t in (normalized, inner)):
                return key
    # 괄호 앞 이름도 맞춘다. 예: 「요구사항(목표)」 → 「요구사항」, 「핵심 요구사항(UI v2.5)」.
    # 다만 「소분류(기능설명)」의 「소분류」가 구분 칸으로 잡히지 않게 ID·명칭·본문 칸만 본다.
    if inner:
        for key in ("source_id", "name", "description"):
            for name in column_map.get(key, ()):
                if base == name.lstrip("=") or (not name.startswith("=") and base.endswith(name)):
                    return key
    return None


def _all_cols(labels: list[str], column_map: dict[str, tuple[str, ...]]) -> tuple[int, ...]:
    """상세 내용(description)으로 읽는 열을 왼쪽부터 모두 고른다."""
    return tuple(
        col for col, label in enumerate(labels) if _label_key(label, column_map) == "description"
    )


def _labels(row: list[str]) -> dict[int, str]:
    return {i: label for i, label in enumerate(row) if label}


def _build_row(
    row: list[_Cell], header: _Header, ref: SourceRef, document_id: str, block_id: str
) -> SourceRequirement | ExtractionIssue | None:
    def get(key: str) -> _Cell:
        col = header.columns.get(key)
        return row[col] if col is not None and col < len(row) else _Cell("")

    if not any(cell.value for cell in row):
        return None  # 빈 행
    source_id, name = get("source_id"), get("name")
    desc_cols = header.description_cols or (
        (header.columns["description"],) if "description" in header.columns else ()
    )
    description = _Cell("\n".join(row[c].value for c in desc_cols if c < len(row) and row[c].value))
    text = description.value or name.value
    if not text:
        return ExtractionIssue(
            ref,
            notice="요구사항명과 상세 내용이 모두 비어 있어 요구사항으로 읽지 못했습니다",
            detail="name·description 칸이 비어 있음 (같은 행의 다른 칸에는 값이 있음)",
        )

    reasons = []
    if not source_id.value:
        reasons.append("요구사항 ID 없음")
    if not description.value:
        reasons.append("상세 내용이 없어 요구사항명을 원문으로 씀")
    if any(cell.uncached_formula for cell in row):
        reasons.append("저장된 결과값이 없는 수식 칸")

    used = {
        header.columns[k]
        for k in ("source_id", "description", "related_ids", "acceptance_level")
        if k in header.columns
    } | set(desc_cols)
    extra = {
        header.labels[col]: cell.value
        for col, cell in enumerate(row)
        if col in header.labels and col not in used and cell.value
    }
    return SourceRequirement(
        document_id=document_id,
        block_id=block_id,
        source_id=source_id.value or None,
        source_ref=ref,
        source_text=text,
        source_acceptance_level=get("acceptance_level").value or None,
        source_related_requirements=get("related_ids").value or None,
        source_extra=extra,
        extraction_status=ExtractionStatus.REVIEW if reasons else ExtractionStatus.PASS,
    )


def _mark_duplicates(requirements: list[SourceRequirement]) -> tuple[SourceRequirement, ...]:
    """같은 원문 ID가 두 번 이상 나오면 모두 확인 대상으로 둔다."""
    counts = Counter(r.source_id for r in requirements if r.source_id)
    return tuple(
        r.evolve(extraction_status=ExtractionStatus.REVIEW)
        if r.source_id and counts[r.source_id] > 1
        else r
        for r in requirements
    )
