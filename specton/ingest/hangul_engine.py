"""한글 문서(.hwp·.hwpx) 읽기 엔진 연결부. 저장소에서 `import rhwp`는 이 파일에만 둔다 (#24).

rhwp-python의 성숙도 위험(11/1 조회):
    PyPI 0.8.1은 Alpha, GitHub 스타 16, 마지막 푸시 9/24(11/1 조회). 엔진 rhwp는 스타 4,043으로
    활발. 그래서 버전을 고정하고 이 모듈 뒤에 숨기며, 연결부가 깨질 때를 위해 `rhwp dump`
    명령줄 예비 경로를 둔다.

이유(왜 한 파일에 가두는가): 엔진이 바뀌거나 깨져도 고칠 곳이 여기 한 곳이다. 나머지 코드
(`hangul.py`)는 아래 엔진 독립 자료형만 본다. 시험도 이 자료형으로 가짜 문서를 만들어
엔진 없이 돈다.

예비 경로 `dump_paragraph_text`: 출력 형식 미확인, 이 컴퓨터에는 rhwp 실행파일 없음. 명령 인자
모양만 시험했고, 문서 읽기(예비 경로로 문서 전체를 읽는 일)는 미구현이다. 엔진 명령줄 `rhwp`는
설치된 wheel에 없고 별도 설치가 필요하다(wheel에는 rhwp-py·rhwp-mcp만 포함).
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rhwp


class HangulFormatError(ValueError):
    """엔진이 파일을 읽지 못함(깨짐·형식 불량·미지원 형식). 파일 쪽 문제다."""


class EngineError(RuntimeError):
    """파일이 아니라 엔진 연결부의 문제(엔진 변경·내부 오류·예비 경로 실행파일 없음 등)."""


@dataclass(frozen=True)
class HangulParagraph:
    """본문 문단 1개. 표가 든 문단은 표 쪽(`HangulTable`)에만 담고 여기에는 넣지 않는다."""

    section: int  # 구역 번호 (0부터)
    paragraph: int  # 엔진의 문단 번호(para_idx). 표 안 문단은 세지 않는다
    text: str


@dataclass(frozen=True)
class HangulCell:
    """표 칸 1개. 병합된 칸은 왼쪽 위 한 칸만 있다(가려진 칸은 목록에 없다)."""

    row: int  # 0부터
    col: int  # 0부터
    row_span: int
    col_span: int
    text: str  # 칸 안 문단을 "\n"으로 이은 글 (원문 그대로, 앞뒤 공백도 그대로)
    has_picture: bool = False  # 칸 안(중첩 표 포함)에 그림이 있는가


@dataclass(frozen=True)
class HangulTable:
    """본문 최상위 표 1개. 표 안의 표(중첩)는 칸 글에 합쳐지고 따로 세지 않는다."""

    section: int
    paragraph: int  # 표가 든 맨 위 문단 번호(para_idx)
    rows: int
    cols: int
    cells: tuple[HangulCell, ...]


@dataclass(frozen=True)
class HangulDocument:
    """문서 순서대로 늘어놓은 문단·표."""

    blocks: tuple[HangulParagraph | HangulTable, ...]

    @property
    def tables(self) -> tuple[HangulTable, ...]:
        return tuple(b for b in self.blocks if isinstance(b, HangulTable))


def _cell_text_and_picture(blocks: list[Any]) -> tuple[str, bool]:
    """칸 안 블록들의 글과 그림 포함 여부. 그림 블록은 text 속성이 없어 getattr로 읽는다."""
    texts: list[str] = []
    picture = False
    for block in blocks:
        kind = type(block).__name__
        if kind == "PictureBlock":
            picture = True
        elif kind == "TableBlock":
            # 중첩 표: 글은 엔진이 만든 표 text를 쓰고, 안쪽 그림도 찾는다
            texts.append(getattr(block, "text", "") or "")
            picture = picture or any(
                _cell_text_and_picture(list(cell.blocks))[1] for cell in block.cells
            )
        else:
            texts.append(getattr(block, "text", "") or "")
    return "\n".join(texts), picture


def _convert_table(block: Any) -> HangulTable:
    cells = []
    for cell in block.cells:
        text, picture = _cell_text_and_picture(list(cell.blocks))
        cells.append(HangulCell(cell.row, cell.col, cell.row_span, cell.col_span, text, picture))
    prov = block.prov
    return HangulTable(prov.section_idx, prov.para_idx, block.rows, block.cols, tuple(cells))


def read_blocks(path: Path) -> HangulDocument:
    """.hwp·.hwpx를 읽어 엔진 독립 자료형으로 돌려준다.

    - 파일을 못 읽으면(깨짐·형식 불량) `HangulFormatError`(ValueError의 하위 종류)
    - 그 밖의 엔진·연결부 오류는 `EngineError`
    - 파일 접근 오류(OSError 계열: 없음·권한·폴더 등)는 엔진 문제가 아니므로 그대로 올린다
    """
    try:
        doc = rhwp.parse(str(path))
        ir = doc.to_ir()
        blocks: list[HangulParagraph | HangulTable] = []
        for block in ir.body:
            kind = type(block).__name__
            if kind == "TableBlock":
                blocks.append(_convert_table(block))
            elif kind in ("PictureBlock", "FieldBlock"):
                continue  # 본문 그림·필드는 요구사항 읽기에 쓰지 않는다
            else:
                text = getattr(block, "text", None)
                prov = getattr(block, "prov", None)
                if text is not None and prov is not None:
                    blocks.append(HangulParagraph(prov.section_idx, prov.para_idx, text))
        return HangulDocument(tuple(blocks))
    except OSError:
        raise
    except ValueError as exc:
        # rhwp-python은 읽지 못한 파일에 ValueError를 낸다(0.8.1에서 빈 파일·깨진 파일·잘린 파일·
        # 깨진 hwpx 모두 확인). 파일 쪽 문제로 분류한다
        raise HangulFormatError(str(exc)) from exc
    except Exception as exc:  # 엔진 API가 바뀌었을 때 등. 연결부 오류로 분류한다
        raise EngineError(f"{type(exc).__name__}: {exc}") from exc


def dump_paragraph_text(path: Path, section: int, paragraph: int) -> str:
    """예비 경로: 엔진 명령줄 `rhwp dump -s <구역> -p <문단> <파일>`의 출력을 가공 없이 돌려준다.

    - 출력 형식 미확인, 이 컴퓨터에는 rhwp 실행파일 없음. 그래서 가공하지 않고 원문 그대로 준다.
    - 시험한 것은 명령 인자 모양뿐이다. 이 경로로 문서 전체를 읽는 일은 미구현이다.
    - 엔진 명령줄 `rhwp`는 설치된 wheel에 없고 별도 설치가 필요하다(wheel에는 rhwp-py·rhwp-mcp만).
    - 실행파일이 없거나 실패하면 `EngineError`.
    """
    command = ["rhwp", "dump", "-s", str(section), "-p", str(paragraph), str(path)]
    try:
        done = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise EngineError(
            "rhwp 실행파일(명령줄)을 찾지 못했어요. 별도 설치가 필요해요(rhwp-python wheel에 없음)."
        ) from exc
    if done.returncode != 0:
        raise EngineError(f"rhwp dump 실패(종료 코드 {done.returncode}): {done.stderr.strip()}")
    return done.stdout
