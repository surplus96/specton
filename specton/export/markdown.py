"""합의한 Markdown 문법만 HTML로 바꾼다 (#13, 기능 명세서 PDF).

기능 명세서 Markdown(#213, `codegen/function_spec.py`)이 쓰는 문법만 다룬다:
제목(`#`·`##`·`###`), 문단, 글머리표(`- `), 굵게(`**`), 인라인 코드(`` ` ``), 파이프 표,
역슬래시 이스케이프(`\\` `\\*` `` \\` `` `\\|`). Markdown 라이브러리를 쓰지 않는다 (#13 R1 정리).

- 그 밖의 문법(인용·링크·이미지·HTML 태그 등)은 해석하지 않고 글자 그대로 보인다.
- 모든 글자는 HTML로 이스케이프한다. 이 모듈이 만드는 태그만 HTML이 된다.
- 표는 행마다 칸 수가 머리글과 같아야 한다. 다르면 문서가 깨진 것이라 멈춘다.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

_ESCAPABLE = frozenset("\\*`|")


@dataclass(frozen=True)
class Heading:
    level: int  # 1~3
    html: str


@dataclass(frozen=True)
class Paragraph:
    html: str


@dataclass(frozen=True)
class BulletList:
    items: tuple[str, ...]  # 항목마다 인라인 HTML


@dataclass(frozen=True)
class Table:
    header: tuple[str, ...]  # 칸마다 인라인 HTML
    rows: tuple[tuple[str, ...], ...]


Block = Heading | Paragraph | BulletList | Table


def parse_blocks(markdown: str) -> list[Block]:
    """문서를 블록 목록으로. 빈 줄이 블록을 나눈다."""
    lines = markdown.splitlines()
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = _heading(line)
        if heading is not None:
            blocks.append(heading)
            i += 1
        elif _is_table_start(lines, i):
            end = i + 2
            while end < len(lines) and lines[end].startswith("|"):
                end += 1
            blocks.append(_table(lines[i:end], first_line=i + 1))
            i = end
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(inline_html(lines[i][2:]))
                i += 1
            blocks.append(BulletList(tuple(items)))
        else:
            text = []
            while i < len(lines) and lines[i].strip() and not _starts_block(lines, i):
                text.append(lines[i].strip())
                i += 1
            blocks.append(Paragraph(inline_html(" ".join(text))))
    return blocks


def inline_html(text: str) -> str:
    """문단·목록·표 칸 안의 글: 이스케이프, `**굵게**`, `` `코드` ``.

    닫히지 않은 기호는 글자로 둔다.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in _ESCAPABLE:
            out.append(html.escape(text[i + 1]))
            i += 2
        elif ch == "`":
            end = text.find("`", i + 1)
            if end == -1:
                out.append("`")
                i += 1
            else:
                out.append(f"<code>{html.escape(text[i + 1 : end])}</code>")
                i = end + 1
        elif text.startswith("**", i):
            end = _closing_bold(text, i + 2)
            if end == -1:
                out.append("**")
                i += 2
            else:
                out.append(f"<strong>{inline_html(text[i + 2 : end])}</strong>")
                i = end + 2
        else:
            out.append(html.escape(ch))
            i += 1
    return "".join(out)


def _closing_bold(text: str, start: int) -> int:
    """`start`부터 이스케이프되지 않은 `**`의 위치. 없으면 -1."""
    i = start
    while i < len(text) - 1:
        if text[i] == "\\" and text[i + 1] in _ESCAPABLE:
            i += 2
        elif text.startswith("**", i):
            return i
        else:
            i += 1
    return -1


def _heading(line: str) -> Heading | None:
    for level in (3, 2, 1):
        mark = "#" * level + " "
        if line.startswith(mark):
            return Heading(level, inline_html(line[len(mark) :].strip()))
    return None


def _is_table_start(lines: list[str], i: int) -> bool:
    return (
        lines[i].startswith("|")
        and i + 1 < len(lines)
        and lines[i + 1].startswith("|")
        and set(lines[i + 1].replace("|", "").strip()) <= {"-", ":", " "}
        and "-" in lines[i + 1]
    )


def _starts_block(lines: list[str], i: int) -> bool:
    line = lines[i]
    return _heading(line) is not None or line.startswith("- ") or _is_table_start(lines, i)


def _cells(row: str) -> list[str]:
    """`| a | b \\| c |` → ["a", "b \\| c"]. 이스케이프한 `|`는 칸을 나누지 않는다."""
    body = row.strip()
    body = body[1:] if body.startswith("|") else body
    cells: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body) and body[i + 1] in _ESCAPABLE:
            current.append(body[i : i + 2])
            i += 2
        elif body[i] == "|":
            cells.append("".join(current).strip())
            current = []
            i += 1
        else:
            current.append(body[i])
            i += 1
    if "".join(current).strip():
        cells.append("".join(current).strip())
    return cells


def _table(rows: list[str], *, first_line: int) -> Table:
    header = _cells(rows[0])
    body = []
    for offset, row in enumerate(rows[2:], start=2):
        cells = _cells(row)
        if len(cells) != len(header):
            raise ValueError(
                f"{first_line + offset}행: 표 칸 수({len(cells)})가"
                f" 머리글({len(header)})과 다릅니다"
            )
        body.append(tuple(inline_html(c) for c in cells))
    return Table(tuple(inline_html(c) for c in header), tuple(body))
