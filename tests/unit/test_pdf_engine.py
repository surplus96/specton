"""PDF 출력 엔진 (#13, ADR-0004 「PDF 출력」 승인 #197, TC-F10·TC-F18 일부).

- 문서 구성: 표지(#14 manifest와 같은 칸) → 전체 관계 개요 → 영역 상세도(키 속성만, 좌우)
  → 테이블 정의서
- 상세도 인쇄 글자가 6pt보다 작으면 경고, 넓은 표는 기준 열 + 20열씩 나눔
- 보안: Mermaid에는 정한 설정만(`secure` 목록), 이름의 지시문 기호·줄바꿈 제거,
  data URI 외 주소 차단
- 초안 표식은 초안에만

WeasyPrint가 필요한 시험은 WeasyPrint를 불러올 수 없는 곳(Windows에 GTK 없음)에서 건너뛴다.
실제 mermaid-cli(`mmdc`) 시험은 `mmdc`가 있을 때만 돈다 (실행 이미지 #25, Docker).
"""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import zlib
from pathlib import Path
from typing import Any

import pytest
from test_erd import MODEL, RELATIONSHIPS

from specton.codegen.erd import _alias, render_erd
from specton.codegen.erd_areas import OTHER_AREA, ErdArea, assign_areas, render_area_erd
from specton.export import pdf
from specton.export.pdf import (
    COVER_FIELDS,
    MERMAID_CONFIG,
    CoverInfo,
    MermaidCli,
    MermaidLayout,
    PdfError,
    build_erd_document,
    erd_sources,
    fit_wide,
    split_columns,
    svg_size,
    table_definition_rows,
    table_html,
)

# 시험 모델(테이블 8개): 기준정보 5개(창고·품목·품목분류·품목사진·품목거래처),
# 수불 2개(입고·입고내역), 기타 1개(거래처)
AREAS = (
    ErdArea("수불", ("입고",)),
    ErdArea("기준정보", ("창고", "품목")),
)
COVER = CoverInfo(
    run_id="00000000-0000-4000-8000-000000000013",
    revision=3,
    model_hash="sha256:abc",
    pack="inventory",
    pack_version="0.1.16",
)


class FakeMermaid:
    """Mermaid 대역: 받은 원문을 남기고, 원문 줄 수에 비례한 크기의 SVG를 돌려준다."""

    def __init__(self, scale: float = 40.0) -> None:
        self.sources: list[str] = []
        self.layouts: list[str] = []
        self.scale = scale

    def __call__(self, source: str, *, layout: MermaidLayout = "dagre") -> str:
        self.sources.append(source)
        self.layouts.append(layout)
        lines = source.count("\n")
        w, h = 200 + lines * self.scale, 100 + lines * self.scale / 2
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="#eee"/><text x="10" y="40">ERD 그림</text></svg>'
        )


def _doc(draft: bool = True, mermaid: Any = None, cover: CoverInfo = COVER) -> pdf.ErdDocument:
    return build_erd_document(
        MODEL, RELATIONSHIPS, AREAS, cover, draft=draft, mermaid=mermaid or FakeMermaid()
    )


# ── 구성 ──────────────────────────────────────────────────


def test_sources_are_overview_then_areas_in_pack_order_then_other() -> None:
    sources = erd_sources(MODEL, RELATIONSHIPS, AREAS)
    assert [(k, t) for k, t, _ in sources] == [
        ("overview", "전체 관계 개요"),
        ("area", "영역 상세 · 수불 (2개)"),
        ("area", "영역 상세 · 기준정보 (5개)"),
        ("area", f"영역 상세 · {OTHER_AREA} (1개)"),
    ]


def test_overview_names_every_relationship_and_is_laid_out_with_elk() -> None:
    """개요도 관계 ID를 쓰고 ELK로 그려 이름이 겹치지 않게 한다. 상세도는 dagre 그대로다 (#261)."""
    sources = erd_sources(MODEL, RELATIONSHIPS, AREAS)
    overview = sources[0][2]
    assert overview.count(' : "REL-') == len(MODEL.foreign_keys)
    mermaid = FakeMermaid()
    _doc(mermaid=mermaid)
    assert mermaid.layouts == ["elk", "dagre", "dagre", "dagre"]


def test_overview_has_no_attributes_and_details_are_key_only_left_to_right() -> None:
    sources = {t: s for _, t, s in erd_sources(MODEL, RELATIONSHIPS, AREAS)}
    overview = sources["전체 관계 개요"]
    assert '"] {' not in overview and "direction" not in overview  # 속성 묶음 없음
    detail = sources["영역 상세 · 기준정보 (5개)"]
    assert detail.splitlines()[1] == "    direction LR"
    assert ' 품목코드 PK "item_cd"' in detail  # 키 속성은 그린다
    assert " 바코드 UK " in detail  # UK도 키
    assert " 단가 " not in detail  # 키가 아닌 속성은 상세도에서 빠지고
    rows = table_definition_rows(MODEL, AREAS)
    assert ["품목", "item", "단가", "untprc", "numeric(12,2)", "", "N"] in rows  # 정의서에는 있다


def test_without_areas_everything_is_one_detail_page() -> None:
    sources = erd_sources(MODEL, RELATIONSHIPS, ())
    assert [t for _, t, _ in sources] == ["전체 관계 개요", f"영역 상세 · {OTHER_AREA} (8개)"]


def test_detail_edges_together_are_all_edges_tc_f10() -> None:
    """영역별 상세도(키 속성만)의 선을 합치면 전체 ERD의 선과 같다."""
    edge = re.compile(r"^    \w+ \S+ \w+ : \"REL-\d+\"$", re.M)
    full = set(edge.findall(render_erd(MODEL, RELATIONSHIPS)))
    details = [s for k, _, s in erd_sources(MODEL, RELATIONSHIPS, AREAS) if k == "area"]
    assert set().union(*(set(edge.findall(d)) for d in details)) == full


def test_cover_uses_manifest_names_and_labels_in_order() -> None:
    page = _doc().html
    labels = [label for _, label in COVER_FIELDS]
    assert labels == ["실행 ID", "리비전", "모델 해시", "도메인 팩", "팩 버전"]
    positions = [page.index(f"<th>{label}</th>") for label in labels]
    assert positions == sorted(positions)
    assert "<td>sha256:abc</td>" in page and "<td>3</td>" in page


def test_figures_follow_the_cover_in_source_order_and_are_data_uri_images() -> None:
    document = _doc()
    page = document.html
    titles = [f.title for f in document.figures]
    positions = [page.index(t) for t in titles]
    assert positions == sorted(positions)
    assert page.index("<h1>") < positions[0] < page.index("테이블 정의서")
    assert page.count('src="data:image/svg+xml;base64,') == len(titles)
    # 엔진이 만든 문서에는 외부 주소가 없다 (모든 src·href가 data URI)
    assert all(u.startswith("data:") for u in re.findall(r'(?:src|href)="([^"]+)"', page))


def test_table_definition_header_is_a_repeating_thead() -> None:
    page = _doc().html
    section = page[page.index("테이블 정의서") :]
    assert "<thead><tr><th>테이블</th><th>테이블 물리명</th>" in section
    rows = table_definition_rows(MODEL, AREAS)
    assert len(rows) == sum(len(t.columns) for t in MODEL.tables)


def test_draft_mark_only_on_drafts() -> None:
    draft, final = _doc(draft=True).html, _doc(draft=False).html
    assert "초안 · 승인 전 · revision 3" in draft and 'class="draft-stamp"' in draft
    assert "초안" not in final and "승인본 · revision 3" in final


def test_small_detail_text_is_warned_with_the_area_name() -> None:
    big = FakeMermaid(scale=400)  # 상세도가 커서 인쇄 글자가 작아짐
    warnings = _doc(mermaid=big).warnings
    assert warnings and all("6pt보다 작습니다" in w for w in warnings)
    assert any("기준정보" in w for w in warnings)
    assert _doc(mermaid=FakeMermaid(scale=1)).warnings == ()  # 작은 그림은 경고 없음


def test_small_overview_text_is_warned_without_asking_to_split_it() -> None:
    """개요도 6pt 미만이면 경고한다. 개요는 나누지 않으므로 상세도를 보라고 안내한다 (#236)."""
    warnings = _doc(mermaid=FakeMermaid(scale=400)).warnings
    overview = [w for w in warnings if w.startswith("전체 관계 개요:")]
    assert len(overview) == 1
    assert "6pt보다 작습니다" in overview[0] and "영역 상세도에서 확인" in overview[0]
    assert "영역 낱말을 나눠" not in overview[0]


def test_text_from_names_is_escaped_in_html() -> None:
    cover = CoverInfo(
        run_id="<script>x</script>", revision=1, model_hash="h", pack="p", pack_version="1"
    )
    page = _doc(cover=cover).html
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert table_html(["<b>"], [["&"]]) == (
        "<table><thead><tr><th>&lt;b&gt;</th></tr></thead><tbody><tr><td>&amp;</td></tr></tbody></table>"
    )


# ── 크기 ──────────────────────────────────────────────────


def test_fit_keeps_small_figures_at_original_size_and_shrinks_big_ones() -> None:
    small = fit_wide('<svg viewBox="0 0 100 50">')
    assert small.text_pt == 12.0  # 16px 그대로
    big = fit_wide('<svg viewBox="0 0 3658 1402">')  # 11/8 실측: 기준정보 상세(전체 속성) 3.4pt
    assert big.text_pt == pytest.approx(3.4, abs=0.1)
    assert big.width_mm <= 297 - 24


@pytest.mark.parametrize(
    "svg", ['<svg width="10">', '<svg viewBox="0 0 0 10">', '<svg viewBox="a b">']
)
def test_svg_without_usable_view_box_is_an_error(svg: str) -> None:
    with pytest.raises(PdfError):
        svg_size(svg)


# ── 넓은 표 (ADR-0004: 기준 열 + 20열씩, 글자 축소 없음) ─────


def _wide(columns: int) -> tuple[list[str], list[list[str]]]:
    header = ["기능 ID", *(f"E{i}" for i in range(1, columns + 1))]
    rows = [[f"FN-{r}", *("C" for _ in range(columns))] for r in range(3)]
    return header, rows


def test_up_to_twenty_entity_columns_stay_in_one_table() -> None:
    header, rows = _wide(20)
    assert split_columns(header, rows) == [(header, rows)]


def test_more_columns_are_split_by_twenty_repeating_the_id_column() -> None:
    header, rows = _wide(45)
    parts = split_columns(header, rows)
    assert [len(h) for h, _ in parts] == [21, 21, 6]
    assert all(h[0] == "기능 ID" and r[0][0] == "FN-0" for h, r in parts)
    assert [c for h, _ in parts for c in h[1:]] == header[1:]  # 빠지거나 겹치는 열 없음


def test_split_rejects_bad_arguments() -> None:
    with pytest.raises(ValueError):
        split_columns(["a"], [], width=0)


# ── 보안: 이름의 지시문 기호 (#190 R1 리뷰) ─────────────────


@pytest.mark.parametrize(
    "name",
    [
        '창고%%{init: {"themeCSS": "body{display:none}"}}%%',
        "창고%%%{init}%%%",
        "창고\nstyle wrhus fill:#f00",
        "창고\r\nclassDef x fill:red",
        "창고\u2028%%{init}%%",  # 줄 구분 문자 U+2028
    ],
)
def test_names_cannot_carry_directives_or_new_lines(name: str) -> None:
    alias = _alias(name)
    assert "%%" not in alias and "\n" not in alias and "\r" not in alias and '"' not in alias
    table = MODEL.tables[-1].model_copy(update={"name": name})
    model = MODEL.model_copy(update={"tables": (*MODEL.tables[:-1], table)})
    for text in (
        render_erd(model, RELATIONSHIPS),
        render_area_erd(model, RELATIONSHIPS, assign_areas(model.tables, AREAS), OTHER_AREA),
    ):
        assert "%%{" not in text
        # 원문 줄은 모두 코드가 정한 모양이다 (사용자 글자가 새 줄을 만들지 못함)
        assert all(re.match(r"^(erDiagram|\s{4,}\S)", line) for line in text.splitlines())
        heads = [line.lstrip() for line in text.splitlines()]
        assert not any(h.startswith(("style", "classDef")) for h in heads)


def test_area_names_in_the_header_comment_cannot_break_the_line() -> None:
    areas = (ErdArea("수불\nstyle wrhus fill:#f00", ("입고",)),)
    split = assign_areas(MODEL.tables, areas)
    text = render_area_erd(MODEL, RELATIONSHIPS, split, split.areas[0][0])
    assert not any(line.lstrip().startswith("style") for line in text.splitlines())


def test_mermaid_gets_only_the_fixed_config_with_secure_keys() -> None:
    secure = set(MERMAID_CONFIG["secure"])
    assert MERMAID_CONFIG["securityLevel"] == "strict"
    # HTML 조각(foreignObject)은 PDF에서 그려지지 않아 상자 글자가 사라진다 → SVG 글자로
    assert MERMAID_CONFIG["htmlLabels"] is False and "htmlLabels" in secure
    # 기본 배치는 dagre. 그림별 배치는 MermaidCli가 정하고 원문 지시문으로는 바꿀 수 없다 (#261)
    assert MERMAID_CONFIG["layout"] == "dagre" and "layout" in secure
    assert {"themeCSS", "themeVariables", "fontFamily", "altFontFamily", "securityLevel"} <= secure


def test_mermaid_cli_passes_the_config_file_and_reads_the_svg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen["args"] = args
        seen["config"] = json.loads(Path(args[args.index("-c") + 1]).read_text(encoding="utf-8"))
        seen["source"] = Path(args[args.index("-i") + 1]).read_text(encoding="utf-8")
        Path(args[args.index("-o") + 1]).write_text('<svg viewBox="0 0 1 1"/>', encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(pdf.subprocess, "run", fake_run)
    svg = MermaidCli(command=("mmdc",), puppeteer_config=Path("p.json"))("erDiagram\n")
    assert svg == '<svg viewBox="0 0 1 1"/>'
    assert seen["args"][0] == "mmdc" and "-p" in seen["args"]
    assert seen["config"] == MERMAID_CONFIG
    assert seen["source"] == "erDiagram\n"

    MermaidCli()("erDiagram\n", layout="elk")
    assert seen["config"] == {**MERMAID_CONFIG, "layout": "elk"}  # 배치만 바뀌고 보안 설정은 그대로


def test_mermaid_cli_failure_is_a_pdf_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(args: list[str], **kwargs: Any) -> None:
        raise subprocess.CalledProcessError(1, args, stderr=b"Parse error")

    monkeypatch.setattr(pdf.subprocess, "run", fail)
    with pytest.raises(PdfError, match="Mermaid"):
        MermaidCli()("erDiagram\n")

    monkeypatch.setattr(pdf.subprocess, "run", lambda args, **kw: None)  # SVG를 만들지 않음
    with pytest.raises(PdfError, match="SVG"):
        MermaidCli()("erDiagram\n")


# ── PDF 변환 (WeasyPrint 필요) ─────────────────────────────


def _weasyprint(*, korean: bool = False) -> Any:
    """WeasyPrint를 불러온다. 없으면 건너뛴다. `korean`이면 한글 폰트도 있어야 한다.

    GitHub CI(ubuntu)에는 Pango는 있지만 한글 폰트(fonts-noto-cjk)가 없다. 한글이 필요한 시험은
    실행 이미지·Docker에서 돌고, 폰트가 없을 때 멈추는지는 CI에서도 시험한다.
    """
    try:
        import weasyprint
    except (ImportError, OSError):  # Windows에서 GTK가 없으면 OSError
        pytest.skip("WeasyPrint를 불러올 수 없는 환경 (Docker·CI 리눅스에서 실행)")
    if korean and not _has_korean_font():
        pytest.skip("한글 폰트(fonts-noto-cjk)가 없는 환경 (실행 이미지·Docker에서 실행)")
    return weasyprint


_KOREAN_FONT: list[bool] = []


def _has_korean_font() -> bool:
    if not _KOREAN_FONT:
        try:
            pdf.html_to_pdf("<p>한글 확인</p>")
            _KOREAN_FONT.append(True)
        except PdfError:
            _KOREAN_FONT.append(False)
    return _KOREAN_FONT[0]


def _inflated(data: bytes) -> bytes:
    """PDF의 압축 스트림을 풀어 이어 붙인다 (글꼴 이름은 압축된 객체 안에 있다)."""
    out = [data]
    for chunk in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            out.append(zlib.decompress(chunk))
        except zlib.error:
            continue
    return b"".join(out)


def _page_texts(document: str) -> list[str]:
    """쪽마다 배치된 글자 (머리글 반복·초안 표식 확인용)."""
    weasyprint = _weasyprint(korean=True)
    rendered = weasyprint.HTML(string=document).render()
    texts = []
    for page in rendered.pages:
        parts = [getattr(box, "text", "") or "" for box in page._page_box.descendants()]
        texts.append(" ".join(p for p in parts if p))
    return texts


def test_pdf_pages_cover_portrait_figures_landscape_and_korean_font() -> None:
    _weasyprint(korean=True)
    result = pdf.html_to_pdf(_doc().html)
    assert result.pdf.startswith(b"%PDF")
    width, height = result.pages[0]
    assert width < height  # 표지는 세로
    figures = len(_doc().figures)
    assert all(w > h for w, h in result.pages[1 : 1 + figures])  # 그림 쪽은 가로
    assert b"Noto" in _inflated(result.pdf)  # 한글 폰트가 PDF에 들어감
    assert result.blocked_urls == ()


def test_missing_glyphs_stop_instead_of_making_a_broken_pdf() -> None:
    """폰트에 없는 글자는 □로 깨진다. 조용히 PDF를 내지 않고 멈춘다 (한글 폰트 미설치 대비)."""
    _weasyprint()
    with pytest.raises(PdfError, match="폰트에 없는 글자") as err:
        pdf.html_to_pdf("<p>\U0010fffd</p>")  # 어떤 폰트에도 없는 사설 영역 글자
    assert "fonts-noto-cjk" in str(err.value)


def test_pdf_blocks_every_url_except_data() -> None:
    _weasyprint()
    page = (
        "<html><head><link rel='stylesheet' href='file:///etc/passwd'>"
        "<style>@import url('https://example.invalid/x.css');</style></head><body>"
        "<img src='http://example.invalid/a.png'><img src='file:///etc/hosts'>"
        "<img src='data:image/svg+xml;base64,"
        "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4='>"
        "</body></html>"
    )
    blocked = pdf.html_to_pdf(page).blocked_urls
    assert set(blocked) >= {
        "file:///etc/passwd",
        "https://example.invalid/x.css",
        "http://example.invalid/a.png",
        "file:///etc/hosts",
    }
    assert not any(u.startswith("data:") for u in blocked)


def test_long_table_repeats_its_header_on_every_page() -> None:
    rows = [["입고", "wrhsg", f"컬럼{i}", f"col_{i}", "varchar(20)", "", "Y"] for i in range(200)]
    page = (
        "<html><head><style>thead{display:table-header-group}</style></head><body>"
        + table_html(pdf.TABLE_HEADER, rows)
        + "</body></html>"
    )
    texts = _page_texts(page)
    assert len(texts) >= 3
    assert all("컬럼 물리명" in t for t in texts)


def test_draft_mark_is_on_every_page_and_absent_from_final() -> None:
    """머리 표식은 세로·가로 모든 쪽의 여백에 글자로 나온다 (배경 표식만으로 통과하지 않게)."""
    draft_pages = _page_texts(_doc(draft=True).html)
    final_pages = _page_texts(_doc(draft=False).html)
    assert len(draft_pages) >= 3
    assert all("초안 · 승인 전 · revision 3" in t for t in draft_pages)
    assert all("승인본 · revision 3" in t for t in final_pages)
    assert not any("초안" in t for t in final_pages)
    assert all("Specton ERD" in t for t in draft_pages)  # 왼쪽 위 문서 이름도 모든 쪽


# ── 실제 mermaid-cli (mmdc가 있을 때만) ──────────────────────


@pytest.mark.skipif(shutil.which("mmdc") is None, reason="mermaid-cli(mmdc)가 없는 환경")
def test_real_mermaid_cli_draws_every_section() -> None:
    # 컨테이너(root)에서는 Chromium 설정이 필요하다: SPECTON_MMDC_PUPPETEER=/etc/puppeteer.json
    config = os.environ.get("SPECTON_MMDC_PUPPETEER")
    cli = MermaidCli(puppeteer_config=Path(config) if config else None)
    for _, _, source in erd_sources(MODEL, RELATIONSHIPS, AREAS):
        svg = cli(source)
        assert "<svg" in svg and svg_size(svg)[0] > 0
        # 상자 글자가 PDF에 남도록 HTML 조각 없이 SVG 글자로 그려진다
        assert "<foreignObject" not in svg and "<text" in svg
        assert "창고" in svg or "입고" in svg or "거래처" in svg


# Mermaid SVG의 관계 이름 상자: edgeLabel 위치 + label 위치 + 배경 rect (mermaid 11.17.2 출력 모양)
_EDGE_LABEL = re.compile(
    r'<g class="edgeLabel" transform="translate\(([-\d.]+), ([-\d.]+)\)">'
    r'<g class="label"[^>]*transform="translate\(([-\d.]+), ([-\d.]+)\)"><g>'
    r'<rect class="background"[^>]*x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)"/>'
    r".*?<tspan[^>]*class=\"text-inner-tspan\"[^>]*>([^<]*)</tspan>"
)


def _label_boxes(svg: str) -> list[tuple[str, float, float, float, float]]:
    """그려진 관계 이름마다 (글자, 왼쪽, 위, 오른쪽, 아래). 빈 이름은 뺀다."""
    boxes = []
    for m in _EDGE_LABEL.finditer(svg):
        ox, oy, ix, iy, rx, ry, w, h = map(float, m.groups()[:8])
        if m.group(9).strip():
            x, y = ox + ix + rx, oy + iy + ry
            boxes.append((m.group(9), x, y, x + w, y + h))
    return boxes


def _overlapping_labels(svg: str) -> list[tuple[str, str]]:
    b = _label_boxes(svg)
    return [
        (p[0], q[0])
        for i, p in enumerate(b)
        for q in b[i + 1 :]
        if p[1] < q[3] and q[1] < p[3] and p[2] < q[4] and q[2] < p[4]
    ]


# 긴 관계선 두 개가 가운데에서 교차하는 개요.
# #261 재현: dagre는 REL-01·REL-04 이름을 같은 자리에 둬 REL-01이 가려진다.
_CROSSING_OVERVIEW = """erDiagram
    wrhus["창고"]
    item["품목"]
    invt_dlng["재고거래내역"]
    invt["재고"]
    bcnc["거래처"]
    wrhus ||..o{ invt_dlng : "REL-01"
    item ||..o{ invt_dlng : "REL-02"
    wrhus ||--o{ invt : "REL-03"
    item ||--o{ invt : "REL-04"
    bcnc ||..o{ invt_dlng : "REL-05"
    bcnc ||..o{ wrhus : "REL-06"
"""


@pytest.mark.skipif(shutil.which("mmdc") is None, reason="mermaid-cli(mmdc)가 없는 환경")
def test_real_mermaid_cli_keeps_crossing_relationship_names_apart_with_elk() -> None:
    config = os.environ.get("SPECTON_MMDC_PUPPETEER")
    cli = MermaidCli(puppeteer_config=Path(config) if config else None)
    svg = cli(_CROSSING_OVERVIEW, layout="elk")
    assert sorted(b[0] for b in _label_boxes(svg)) == [f"REL-{i:02d}" for i in range(1, 7)]
    assert _overlapping_labels(svg) == []


# ── 동시 렌더링 (#209 R1 리뷰: 다른 렌더링의 글자 깨짐 경고가 섞이지 않음) ─────


_NOTDEF = '.notdef glyph rendered for Unicode string unsupported by fonts: "{}"'


def test_missing_glyph_handler_ignores_warnings_from_other_threads() -> None:
    """핸들러는 경고를 낸 스레드에서 모으는 중(`collect`)일 때만 넘긴다. WeasyPrint 없이도 돈다."""
    logger = logging.getLogger("weasyprint")
    handler = pdf._MissingGlyphs()
    logger.addHandler(handler)
    try:
        logger.warning(_NOTDEF.format("다"))  # 모으는 중이 아님: 버린다
        with handler.collect() as chars:
            other = threading.Thread(target=lambda: logger.warning(_NOTDEF.format("가")))
            other.start()
            other.join()
            assert chars == set()  # 다른 스레드 경고는 무시
            logger.warning(_NOTDEF.format("나"))
        assert chars == {"나"}  # 이 스레드 경고만 모은다
    finally:
        logger.removeHandler(handler)


def _glyph_handlers() -> list[logging.Handler]:
    handlers = logging.getLogger("weasyprint").handlers
    return [h for h in handlers if isinstance(h, pdf._MissingGlyphs)]


def _run_into(results: dict[str, Any], name: str, document: str) -> None:
    try:
        results[name] = pdf.html_to_pdf(document)
    except PdfError as exc:
        results[name] = exc


def test_concurrent_renders_fail_only_the_document_with_missing_glyphs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """정상 문서 렌더링이 시작한 뒤 멈춘 사이 다른 스레드가 깨지는 문서를 렌더링해도
    정상 문서는 PDF가 나오고, 깨지는 문서만 PdfError다 (R1 재현 순서 그대로)."""
    weasyprint = _weasyprint()
    original = weasyprint.HTML.render
    ascii_ready, release = threading.Event(), threading.Event()

    def render(self: Any, *args: Any, **kwargs: Any) -> Any:
        if threading.current_thread().name == "ascii":
            ascii_ready.set()  # 모으기를 시작하고 렌더링 직전
            assert release.wait(30)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(weasyprint.HTML, "render", render)
    results: dict[str, Any] = {}

    ascii_doc = threading.Thread(
        target=_run_into, args=(results, "ascii", "<p>plain ascii</p>"), name="ascii"
    )
    ascii_doc.start()
    assert ascii_ready.wait(30)
    _run_into(
        results, "broken", "<p>\U0010fffd</p>"
    )  # 어떤 폰트에도 없는 글자, 이 스레드에서 렌더링
    release.set()
    ascii_doc.join(30)

    assert isinstance(results["broken"], PdfError)
    assert isinstance(results["ascii"], pdf.PdfResult), results["ascii"]
    assert results["ascii"].pdf.startswith(b"%PDF")
    assert len(_glyph_handlers()) == 1  # 상시 핸들러 하나만


def test_a_render_ending_while_another_logs_does_not_hide_its_missing_glyphs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#209 R1 두 번째 재현: 깨지는 문서의 경고를 로거가 핸들러에 넘기는 도중 정상 문서 렌더링이
    끝나도 깨지는 문서는 PdfError다. 렌더링마다 핸들러를 떼던 예전 코드는 로거가 도는 핸들러 목록이
    바뀌어 깨지는 문서 쪽 핸들러를 건너뛰고 PDF가 성공으로 나왔다.
    `handle`·`emit`은 원래 동작을 그대로 부르고 Event로 순서만 맞춘다.

    멈추는 곳은 핸들러 잠금(`Handler.handle`이 `emit` 전에 잡는다) 바깥이다. 잠금 안에서 멈추면
    정상 문서가 그 사이 남기는 WeasyPrint 경고(CI의 HarfBuzz-Subset 안내 등)가 잠금에서 기다려
    시험이 멈춘다. 그 경우도 시험하려고 정상 문서가 경고 하나를 직접 남긴다."""
    weasyprint = _weasyprint()
    original_render = weasyprint.HTML.render
    original_handle = pdf._MissingGlyphs.handle
    ascii_ready, ascii_go = threading.Event(), threading.Event()
    broken_in_handler, broken_go = threading.Event(), threading.Event()

    def render(self: Any, *args: Any, **kwargs: Any) -> Any:
        if threading.current_thread().name == "ascii":
            ascii_ready.set()
            assert ascii_go.wait(30)
            logging.getLogger("weasyprint").warning("정상 문서 쪽 경고")  # 글자 깨짐과 무관
        return original_render(self, *args, **kwargs)

    def handle(self: Any, record: logging.LogRecord) -> Any:
        if threading.current_thread().name == "broken" and not broken_in_handler.is_set():
            broken_in_handler.set()  # 로거가 첫 핸들러를 처리하는 중
            assert broken_go.wait(30)
        return original_handle(self, record)

    monkeypatch.setattr(weasyprint.HTML, "render", render)
    monkeypatch.setattr(pdf._MissingGlyphs, "handle", handle)
    results: dict[str, Any] = {}
    ascii_doc = threading.Thread(
        target=_run_into, args=(results, "ascii", "<p>plain ascii</p>"), name="ascii"
    )
    broken_doc = threading.Thread(
        target=_run_into, args=(results, "broken", "<p>\U0010fffd</p>"), name="broken"
    )
    ascii_doc.start()
    assert ascii_ready.wait(30)  # 정상 문서가 먼저 시작
    broken_doc.start()
    assert broken_in_handler.wait(30)  # 깨지는 문서의 경고가 핸들러에 넘어가는 중
    ascii_go.set()
    ascii_doc.join(30)  # 그 사이 정상 문서는 끝까지 (예전 코드는 여기서 핸들러를 뗐다)
    ascii_finished = not ascii_doc.is_alive()
    broken_go.set()
    broken_doc.join(30)

    assert ascii_finished, "정상 문서가 깨지는 문서의 경고 처리를 기다리며 멈췄다"

    assert isinstance(results["ascii"], pdf.PdfResult), results["ascii"]
    assert isinstance(results["broken"], PdfError), results["broken"]
    assert len(_glyph_handlers()) == 1


def test_rendering_does_not_change_the_weasyprint_handler_list() -> None:
    """핸들러는 처음 한 번만 걸린다. 그 뒤 렌더링은 로거의 핸들러 목록을 바꾸지 않는다."""
    _weasyprint()
    pdf.html_to_pdf("<p>first</p>")
    before = list(logging.getLogger("weasyprint").handlers)
    pdf.html_to_pdf("<p>second</p>")
    with pytest.raises(PdfError):
        pdf.html_to_pdf("<p>\U0010fffd</p>")
    assert logging.getLogger("weasyprint").handlers == before
