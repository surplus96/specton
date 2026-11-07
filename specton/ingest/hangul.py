"""한글(.hwp·.hwpx) 요구사항 상세표를 원문 한 건씩(`SourceRequirement`)으로 읽는다 (#24, ADR-0004).

이음 임시 제안, 팀 결정 전: 아래 규칙은 #24 할 일 1번을 먼저 진행하며 정한 제안이다.

- 요구사항 1건 = 상세표 1개다(한글은 표가 필수라는 결정). 상세표는 「요구사항 고유번호」(또는
  「고유번호」) 라벨 칸의 같은 행 오른쪽에 값 칸이 있는 표다.
- 표는 칸 순서대로 훑으며 「라벨 칸 → 같은 행에서 바로 오른쪽 값 칸」 짝으로 읽는다. 한 행에
  라벨·값 쌍이 둘이어도(경남로봇랜드 모양) 같은 규칙이다. 오른쪽 칸이 또 라벨이면 짝이 아니다.
- 「요구사항 목록표」(머리 행에 고유번호와 요구사항명 칸이 함께 있는 큰 표)는 요구사항이 아니라
  대조용이다. 상세표에 같은 고유번호가 있으면 상세표만 내고, 목록표에만 있는 고유번호는
  요구사항명만으로 `review` 블록을 낸다(조용히 버리지 않음, ADR-0015).
- 목록표의 생략 표시 줄(번호 칸에 숫자가 하나도 없고 이름 칸도 빈 행. 예: 「...」「..」)은 내용이
  없어 블록으로 만들지 않고 건너뛴다. 번호가 숫자 없는 글이어도 이름이 있으면 review로 남긴다.
  한계: 건너뛴 줄의 개수는 결과에 남지 않는다. `ExtractionIssue`는 원문 한 곳을 가리키는 「확인
  필요」 1건이라 개수 안내용으로 쓰면 화면의 확인 필요 건수가 부풀어, 쓰지 않았다(이음 임시 제안).
- 원문 위치(`SourceRef`)는 아래 `_source_ref`의 독스트링을 본다.
- `source_text`는 「정의」 값과 「세부내용」 값을 줄바꿈으로 이은 글이다. 칸마다 글자는 원문
  그대로(앞뒤 공백만 뺌, tabular와 같음)다.
- 판정은 `pass`와 `review`만 만든다. `fail`을 정하는 기준은 #24 시험 뒤 정한다고 계약
  (`ExtractionStatus`)에 적혀 있어, 이번에는 기준 없이 `fail`을 만들지 않는다.
- 파일 단위로 멈추는 경우(`UnsupportedInput`): ① 엔진이 파일을 못 읽음(깨짐·형식 불량)
  ② 읽었지만 상세표가 하나도 없음 ③ 엔진 연결부 오류·표 해석 오류. 빈 결과나 `pass`로 넘기지 않는다.
- 암호화·배포용 문서(할 일 4번), 취소선, HWP 5.0 직접 비교는 이번 범위가 아니다.
"""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from specton.contracts.base import ExtractionStatus, SourceRef
from specton.contracts.requirements import SourceRequirement
from specton.ingest.hangul_engine import (
    HangulCell,
    HangulFormatError,
    HangulTable,
    read_blocks,
)
from specton.ingest.tabular import (
    NOTICE_DUPLICATE,
    NOTICE_EMPTY,
    NOTICE_NAME_ONLY,
    NOTICE_NO_ID,
    TabularResult,
    UnsupportedInput,
)

# 판정 이유 문장. tabular와 같은 명사형이며 고객 원문은 넣지 않는다
NOTICE_LIST_ONLY = "상세표 없이 목록표에만 있어 요구사항명을 원문 문장으로 씀"
NOTICE_PICTURE = "표 칸에 그림이 있어 글로 읽지 못한 내용이 있을 수 있음"
NOTICE_BROKEN_MERGE = "표의 칸 병합이 달라 값 칸을 찾지 못한 라벨이 있음"

# 라벨 글자(공백을 모두 뺀 것) → 이 코드 안의 이름. 두 원문(KITECH·경남로봇랜드)을 훑어 정했다.
# 「요구사항 상세설명」 같은 묶음 칸은 값이 없는 머리라서 라벨로 치지 않는다.
_LABELS = {
    "요구사항분류": "category",
    "요구사항고유번호": "id",
    "고유번호": "id",
    # aT 비축 RFP 상세표 표기(붙여 쓴 「요구사항번호」). 목록표 머리에서만 쓰던 라벨을
    # 상세표에도 인정
    "요구사항번호": "id",
    "요구사항명칭": "name",
    "요구사항명": "name",
    "응락수준": "level",
    "정의": "definition",
    "세부내용": "detail",
    "산출정보": "output",
    # 엑셀 읽기(`tabular.py`의 related_ids 칸, `column_map.yaml`)와 같은 정보를 내려고 한글 상세표의
    # 「관련 요구사항」 칸도 읽는다. 값은 원문 글 그대로 두고(엑셀도 그대로) 해석하지 않는다.
    "관련요구사항": "related",
}
# source_extra에 담을 때 쓰는 칸 이름(원문 라벨 표기)
_EXTRA_NAMES = {"category": "요구사항 분류", "name": "요구사항 명칭", "output": "산출정보"}


# 목록표 머리의 번호 칸 라벨(공백 제거·소문자 비교). 상세표 라벨(_LABELS)과 따로 둔다:
# 「번호」「ID」는 상세표 안에서는 라벨이 아니므로, 같은 행에 요구사항명 칸이 있는 목록표
# 머리에서만 번호 칸으로 본다.
_LIST_ID_LABELS = frozenset(
    {"고유번호", "요구사항고유번호", "번호", "id", "요구사항id", "요구사항번호"}
)


@dataclass(frozen=True)
class _Detail:
    """상세표 1개를 읽은 중간 결과."""

    table: HangulTable
    index: int  # 구역 안 표 순번(0부터)
    values: dict[str, HangulCell]  # 라벨 이름 → 값 칸 (짝을 찾은 것만)
    id_cell: HangulCell | None  # 고유번호 값 칸(없으면 병합이 깨진 표)


def _key(text: str) -> str | None:
    """칸 글자가 라벨이면 라벨 이름, 아니면 None. 공백·줄바꿈은 무시한다."""
    return _LABELS.get("".join(text.split()))


def _column_letters(col: int) -> str:
    """열 번호(0부터)를 엑셀식 열 문자로(0=A, 25=Z, 26=AA). 계약의 CellAddress 형식이다."""
    letters = ""
    col += 1
    while col:
        col, rest = divmod(col - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def _source_ref(table: HangulTable, index: int, cell: HangulCell) -> SourceRef:
    """원문 위치를 만든다.

    `paragraph`에는 엔진의 para_idx(KITECH 347·359처럼 표가 든 맨 위 문단 번호, 표 안 문단은
    세지 않음), `table`은 그 구역 안 표의 순번(0부터, 문서 순서)이다. 요구사항 본문이 여러
    칸(정의·세부내용)에 걸쳐 있어도 위치(`cell`)는 고유번호 값 칸 한 칸이다(이음 임시 제안, 팀 결정
    전). 쪽 번호는 넣지 않는다: HWPX에 저장되지 않고 rhwp의 쪽 번호는 긴 문서에서 한글과 어긋남이
    확인됐다.
    """
    address = f"{_column_letters(cell.col)}{cell.row + 1}"
    return SourceRef(
        file_format="hwpx",
        section=table.section,
        paragraph=table.paragraph,
        table=index,
        cell=address,
    )


def _grid(table: HangulTable) -> dict[tuple[int, int], HangulCell]:
    return {(c.row, c.col): c for c in table.cells}


def _list_header(table: HangulTable) -> tuple[int, int, int] | None:
    """목록표 머리 (행, 번호 열, 명칭 열).

    한 행에 번호 칸과 명칭 칸이 함께 있고 아래에 번호꼴 값이 있으면 목록표다.

    상세표에서는 고유번호 라벨과 명칭 라벨이 서로 다른 행에 있으므로 구분된다.
    """
    by_row: dict[int, dict[str, int]] = {}
    for cell in table.cells:
        if "".join(cell.text.split()).lower() in _LIST_ID_LABELS:
            by_row.setdefault(cell.row, {}).setdefault("id", cell.col)
        elif _key(cell.text) == "name":
            by_row.setdefault(cell.row, {}).setdefault("name", cell.col)
    grid = _grid(table)
    for row in sorted(by_row):
        found = by_row[row]
        if "id" not in found or "name" not in found:
            continue
        # 머리 아래 행에서 번호꼴 값(숫자가 든 글)이 하나라도 나와야 목록표다.
        # 라벨만 우연히 한 행에 모인 다른 표를 목록표로 오인하지 않기 위함이다
        below = (grid.get((r, found["id"])) for r in range(row + 1, table.rows))
        if any(c is not None and any(ch.isdigit() for ch in c.text) for c in below):
            return row, found["id"], found["name"]
    return None


def _read_detail(table: HangulTable, index: int) -> _Detail | None:
    """상세표라면 라벨→값 짝을 읽는다. 고유번호 라벨이 없는 표는 None(요구사항 표가 아님)."""
    grid = _grid(table)
    values: dict[str, HangulCell] = {}
    has_id_label = False
    for cell in sorted(table.cells, key=lambda c: (c.row, c.col)):
        key = _key(cell.text)
        if key is None:
            continue
        if key == "id":
            has_id_label = True
        # 라벨 칸이 차지한 열 바로 다음 칸이 같은 행의 값 칸이다
        value = grid.get((cell.row, cell.col + cell.col_span))
        if value is None or _key(value.text) is not None:
            continue  # 오른쪽 칸이 없거나 또 라벨이면 짝이 아니다(예: 묶음 칸 옆의 「정의」)
        values.setdefault(key, value)
    if not has_id_label:
        return None
    return _Detail(table, index, values, values.get("id"))


def _text(cell: HangulCell | None) -> str:
    return cell.text.strip() if cell else ""


def _location_id(table: HangulTable) -> str:
    """고유번호가 없을 때의 block_id: `S{구역}-P{문단}` (구역 번호 + 문단 번호)."""
    return f"S{table.section}-P{table.paragraph}"


def _build_detail(
    detail: _Detail, document_id: str, block_id: str, duplicated: bool
) -> SourceRequirement:
    """상세표 1개 → 원문 한 건. 판정 이유는 이유마다 한 줄이다."""
    table, values = detail.table, detail.values
    anchor = detail.id_cell
    source_id = _text(anchor) or None
    parts = [_text(values.get(k)) for k in ("definition", "detail")]
    body = "\n".join(p for p in parts if p)
    name = _text(values.get("name"))
    # 정의·세부내용이 있으면 pass 후보. 둘 다 비면 명칭만 쓰고 review, 명칭도 없으면 글 없음 review
    text: str | None
    if body:
        text, reasons = body, []
    elif name:
        text, reasons = name, [NOTICE_NAME_ONLY]
    else:
        text, reasons = None, [NOTICE_EMPTY]
    if source_id is None:
        reasons.append(NOTICE_NO_ID)
    if duplicated:
        reasons.append(NOTICE_DUPLICATE)
    if any(cell.has_picture for cell in table.cells):
        reasons.append(NOTICE_PICTURE)
    # 고유번호·정의·세부내용·명칭 라벨은 있는데 값 칸을 못 찾으면 병합이 깨진 표다
    labels = {k for c in table.cells if (k := _key(c.text)) is not None}
    if any(k not in values for k in labels & {"id", "definition", "detail", "name"}):
        reasons.append(NOTICE_BROKEN_MERGE)
    # 값 칸을 못 찾은 고유번호는 위치를 고유번호 칸으로 잡을 수 없어 표의 첫 칸을 쓴다
    ref_cell = anchor or min(table.cells, key=lambda c: (c.row, c.col))
    extra = {
        label: value for key, label in _EXTRA_NAMES.items() if (value := _text(values.get(key)))
    }
    return SourceRequirement(
        document_id=document_id,
        block_id=block_id,
        source_id=source_id,
        source_ref=_source_ref(table, detail.index, ref_cell),
        source_text=text,
        source_acceptance_level=_text(values.get("level")) or None,
        # 「관련 요구사항」 칸 원문. 비어 있으면 None(엑셀 읽기와 같음)
        source_related_requirements=_text(values.get("related")) or None,
        source_extra=extra,
        extraction_status=ExtractionStatus.REVIEW if reasons else ExtractionStatus.PASS,
        notice="\n".join(reasons) or None,
    )


def _list_only(
    tables: list[tuple[HangulTable, int]], detail_ids: set[str], document_id: str
) -> list[tuple[SourceRequirement, str | None]]:
    """목록표에만 있는 고유번호 → 이름만으로 review 블록. (블록, 고유번호) 쌍을 돌려준다."""
    out: list[tuple[SourceRequirement, str | None]] = []
    for table, index in tables:
        header = _list_header(table)
        if header is None:
            continue
        head_row, id_col, name_col = header
        grid = _grid(table)
        for row in sorted({c.row for c in table.cells if c.row > head_row}):
            id_cell = grid.get((row, id_col))
            source_id = _text(id_cell)
            if id_cell is None or not source_id or source_id in detail_ids:
                continue
            name = _text(grid.get((row, name_col)))
            if not name and not any(ch.isdigit() for ch in source_id):
                # 생략 표시 줄(「...」 등)은 내용이 없어 건너뜀. 이름이 있으면 review로 남김
                continue
            out.append(
                (
                    SourceRequirement(
                        document_id=document_id,
                        block_id=source_id,
                        source_id=source_id,
                        source_ref=_source_ref(table, index, id_cell),
                        source_text=name or None,
                        extraction_status=ExtractionStatus.REVIEW,
                        notice=NOTICE_LIST_ONLY if name else NOTICE_EMPTY,
                    ),
                    source_id,
                )
            )
    return out


def _unsupported_tables() -> UnsupportedInput:
    return UnsupportedInput(
        "요구사항 표를 찾지 못했어요. 요구사항 상세표가 있는 한글 파일인지 확인해 주세요.",
        "「요구사항 고유번호」(또는 「고유번호」) 칸 옆에 값이 있는 표를 하나도 찾지 못했어요. "
        "요구사항을 표로 적은 한글 파일(.hwp·.hwpx)만 읽어요. 알아보는 칸 이름: 요구사항 분류, "
        "요구사항 고유번호, 요구사항 명칭, 응락수준, 정의, 세부내용, 산출정보.",
    )


def read_hangul(path: Path, document_id: str) -> TabularResult:
    """한글 파일(.hwp·.hwpx)의 요구사항 상세표를 읽는다. `read_excel`과 같은 모양의 결과를 준다.

    원문 위치는 `source_ref`(구역·문단·표 순번·고유번호 값 칸)다. `paragraph`에는 엔진의
    para_idx(KITECH 347·359처럼 표가 든 맨 위 문단 번호), `table`은 그 구역 안 표의 순번(0부터)이며,
    요구사항 본문이 여러 칸(정의·세부내용)에 걸쳐 있어도 `cell`은 고유번호 값 칸 한 칸이다.
    """
    try:
        document = read_blocks(path)
    except HangulFormatError as exc:
        # 엔진이 파일을 읽지 못함(빈 파일·깨진 파일·미지원 형식 등)
        raise UnsupportedInput(
            "파일을 열 수 없어요. 한글에서 열리는지 확인하고 .hwpx로 다시 저장해 올려 주세요.",
            f"파일 안의 구조를 읽지 못했어요(손상됐거나 한글 문서가 아닌 파일일 수 있어요). {exc}",
        ) from exc
    except FileNotFoundError:
        raise
    except OSError as exc:
        # 권한 없음·폴더 경로 등 파일 접근 오류. 엔진 연결 오류와 구분해 안내한다
        raise UnsupportedInput(
            "파일을 열 수 없어요. 파일 권한이나 경로를 확인해 주세요.",
            f"파일에 접근하지 못했어요: {type(exc).__name__}",
        ) from exc
    except Exception as exc:  # EngineError 포함: 엔진 연결부 오류는 빈 결과로 넘기지 않는다
        raise UnsupportedInput(
            "한글 파일을 읽는 도중 문제가 생겼어요. 잠시 뒤 다시 시도하거나 .hwpx로 저장해 주세요.",
            f"읽기 엔진 연결 오류: {type(exc).__name__}: {exc}",
        ) from exc

    try:
        return _read_tables(document.tables, document_id)
    except UnsupportedInput:
        raise
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        # 표 구조가 예상과 달라 해석하지 못함. 조용히 빈 결과나 pass로 두지 않는다
        raise UnsupportedInput(
            "표의 구조를 해석하지 못했어요. 한글에서 표를 확인하고 .hwpx로 다시 저장해 주세요.",
            f"표 해석 오류: {type(exc).__name__}: {exc}",
        ) from exc


def _read_tables(tables: tuple[HangulTable, ...], document_id: str) -> TabularResult:
    """표 목록(문서 순서)에서 상세표를 모아 원문으로 만든다."""
    # 구역 안 표 순번(0부터)을 문서 순서로 매긴다
    per_section: Counter[int] = Counter()
    numbered: list[tuple[HangulTable, int]] = []
    for table in tables:
        numbered.append((table, per_section[table.section]))
        per_section[table.section] += 1

    details: list[_Detail] = []
    list_tables: list[tuple[HangulTable, int]] = []
    for table, index in numbered:
        if _list_header(table) is not None:
            list_tables.append((table, index))  # 목록표는 상세표로 읽지 않는다
            continue
        detail = _read_detail(table, index)
        if detail is not None:
            details.append(detail)
    if not details:
        raise _unsupported_tables()

    counts = Counter(_text(d.id_cell) for d in details if _text(d.id_cell))
    requirements: list[SourceRequirement] = []
    for detail in details:
        source_id = _text(detail.id_cell)
        duplicated = bool(source_id) and counts[source_id] > 1
        # 같은 고유번호가 두 번 이상이면 block_id가 겹치므로 위치 형식을 쓴다
        block_id = source_id if source_id and not duplicated else _location_id(detail.table)
        requirements.append(_build_detail(detail, document_id, block_id, duplicated))

    only = _list_only(list_tables, set(counts), document_id)
    only_counts = Counter(sid for _, sid in only)
    for req, sid in only:
        if sid is not None and only_counts[sid] > 1:  # 목록표에서 같은 고유번호가 반복됨
            req = req.evolve(
                block_id=f"{sid}@S{req.source_ref.section}-P{req.source_ref.paragraph}"
                f"-T{req.source_ref.table}-{req.source_ref.cell}",
                notice="\n".join(filter(None, (req.notice, NOTICE_DUPLICATE))),
            )
        requirements.append(req)

    requirements.sort(
        key=lambda r: (
            r.source_ref.section or 0,
            r.source_ref.paragraph or 0,
            r.source_ref.table or 0,
        )
    )
    return TabularResult(_unique_block_ids(requirements))


def _unique_block_ids(requirements: list[SourceRequirement]) -> tuple[SourceRequirement, ...]:
    """block_id가 겹치면(같은 문단에 표가 둘 등) 표 순번을 붙여 구분한다."""
    counts = Counter(r.block_id for r in requirements)
    return tuple(
        r.evolve(block_id=f"{r.block_id}-T{r.source_ref.table}") if counts[r.block_id] > 1 else r
        for r in requirements
    )
