"""기능 명세서 PDF (#13 공용 엔진, #213 Markdown 입력).

- 합의한 Markdown 문법만 HTML로 바꾸는지, 그 밖의 글은 글자 그대로인지(`markdown.py`)
- 넓은 CRUD 표를 가로 쪽에 두고 기능 열을 남긴 채 20열씩 나누는지
- 실제 PDF(한글 폰트가 있는 실행 이미지에서만): 쪽 방향, 글자, 초안 표식, 머리글 반복
"""

from __future__ import annotations

import re

import pytest
from test_function_spec import _design, _entity
from test_pdf_engine import _page_texts, _weasyprint

from specton.codegen.function_spec import render_function_spec
from specton.contracts import Function
from specton.export.markdown import BulletList, Heading, Paragraph, Table, inline_html, parse_blocks
from specton.export.pdf import CoverInfo, build_function_spec_html, render_function_spec_pdf

COVER = CoverInfo(
    run_id="00000000-0000-4000-8000-000000000014",
    revision=2,
    model_hash="sha256:abc",
    pack="inventory",
    pack_version="0.1.16",
    title="기능 명세서",
)


# ── 합의한 문법 → HTML ───────────────────────────────────


def test_inline_bold_code_and_escapes() -> None:
    assert inline_html("**설명:** 입고") == "<strong>설명:</strong> 입고"
    assert inline_html("`REQ-01`, `REQ-02`") == "<code>REQ-01</code>, <code>REQ-02</code>"
    # 역슬래시 이스케이프는 글자로 (#213 _text·_cell과 짝)
    assert inline_html(r"a\*b\`c\\d\|e") == "a*b`c\\d|e"


def test_everything_else_is_plain_escaped_text() -> None:
    assert inline_html("<script>x</script>") == "&lt;script&gt;x&lt;/script&gt;"
    assert inline_html("[링크](http://x) ![그림](y)") == "[링크](http://x) ![그림](y)"
    assert inline_html("닫히지 않은 **굵게와 `코드") == "닫히지 않은 **굵게와 `코드"
    blocks = parse_blocks("> 인용\n\n1. 번호\n\n---")
    assert all(isinstance(b, Paragraph) for b in blocks)
    assert [b.html for b in blocks if isinstance(b, Paragraph)] == ["&gt; 인용", "1. 번호", "---"]


def test_blocks_of_the_real_function_spec() -> None:
    blocks = parse_blocks(render_function_spec(_design()))
    headings = [(b.level, b.html) for b in blocks if isinstance(b, Heading)]
    assert headings[:3] == [(1, "기능 명세서"), (2, "문서 정보"), (2, "기능 목록")]
    assert (3, "FUNC-02 재고 조회 | 출력") in headings  # 이름 속 `|`는 글자
    tables = [b for b in blocks if isinstance(b, Table)]
    info, functions, crud = tables
    assert info.header == ("항목", "값") and len(info.rows) == 5
    assert functions.rows[1][1] == "재고 조회 | 출력"  # 표 칸 속 이스케이프한 `|`
    assert crud.header == ("기능", "창고", "입고이력")
    assert any(isinstance(b, BulletList) and len(b.items) == 5 for b in blocks)


def test_table_rows_must_match_the_header() -> None:
    with pytest.raises(ValueError, match="표 칸 수"):
        parse_blocks("| a | b |\n|---|---|\n| 1 |")


# ── 문서 조립 ─────────────────────────────────────────────


def test_html_keeps_the_spec_and_only_safe_urls() -> None:
    page = build_function_spec_html(render_function_spec(_design()), COVER, draft=True)
    assert "<title>Specton 기능 명세서</title>" in page
    assert "<h1>기능 명세서</h1>" in page and "<code>REQ-01</code>" in page
    assert "초안 · 승인 전 · revision 2" in page and 'class="draft-stamp"' in page
    assert re.findall(r'(?:src|href)="([^"]+)"', page) == []  # 외부 주소가 없다
    final = build_function_spec_html(render_function_spec(_design()), COVER, draft=False)
    assert "초안" not in final and "승인본 · revision 2" in final


def test_small_crud_matrix_stays_on_the_portrait_page() -> None:
    page = build_function_spec_html(render_function_spec(_design()), COVER, draft=True)
    assert 'class="wide"' not in page  # 기능 + 엔티티 2 = 3열


def _wide_design(entity_count: int):  # type: ignore[no-untyped-def]
    entities = tuple(_entity(i, f"엔티티{i}") for i in range(1, entity_count + 1))
    function = Function(
        id="FUNC-01",
        name="전체 조회",
        description="모두 조회한다",
        req_ids=("REQ-01",),
        entity_ops=tuple({"entity_id": e.id, "operations": ("R",)} for e in entities),
    )
    return _design(entities=entities, functions=(function,))


def test_wide_crud_matrix_goes_landscape_and_splits_by_twenty_keeping_the_function_column() -> None:
    page = build_function_spec_html(render_function_spec(_wide_design(25)), COVER, draft=True)
    wide = page[page.index('<section class="wide">') :]
    assert wide.startswith('<section class="wide"><h2>CRUD 매트릭스</h2>')  # 제목도 같은 쪽
    tables = re.findall(r"<thead><tr>(.*?)</tr></thead>", wide)
    assert len(tables) == 2 and "열 1/2" in wide and "열 2/2" in wide
    first, second = (re.findall(r"<th>(.*?)</th>", t) for t in tables)
    assert first[0] == second[0] == "기능"  # 기능 열을 반복
    assert len(first) == 21 and len(second) == 6  # 기능 + 20 / 기능 + 5


# ── 실제 PDF (한글 폰트가 있는 실행 이미지에서) ─────────────────


def test_real_pdf_has_korean_text_landscape_crud_and_the_draft_mark() -> None:
    _weasyprint(korean=True)
    markdown = render_function_spec(_wide_design(25))
    result = render_function_spec_pdf(markdown, COVER, draft=True)
    assert result.pdf.startswith(b"%PDF-") and not result.blocked_urls
    landscape = [w > h for w, h in result.pages]
    assert landscape[0] is False and any(landscape)  # 본문은 세로, CRUD는 가로
    texts = _page_texts(build_function_spec_html(markdown, COVER, draft=True))
    assert "기능 명세서" in texts[0] and "FUNC-01" in "".join(texts)
    assert all("초안 · 승인 전 · revision 2" in t for t in texts)


def test_real_pdf_repeats_the_header_of_a_long_table() -> None:
    _weasyprint(korean=True)
    functions = tuple(
        Function(id=f"FUNC-{i:02}", name=f"기능{i}", description="설명", req_ids=("REQ-01",))
        for i in range(1, 121)
    )
    markdown = render_function_spec(_design(functions=functions))
    texts = _page_texts(build_function_spec_html(markdown, COVER, draft=False))
    list_pages = [t for t in texts if "FUNC-0" in t or "FUNC-1" in t]
    assert len(list_pages) >= 2
    assert all("기능 ID" in t for t in list_pages[:2])  # 기능 목록 머리글이 다음 쪽에도
