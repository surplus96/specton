"""PDF 출력 엔진 (#13, ADR-0004 「PDF 출력」 승인 #197).

정리된 모델(`NormalizedModel`)과 설계 관계로 ERD PDF를 만든다. 기능 명세서(#14)도 같은 엔진을
쓸 수 있게 문서 조립(HTML)과 PDF 변환(WeasyPrint)을 나눠 둔다.

ERD PDF 구성 (ADR-0004):
1. 표지: 실행 정보 표 (#14 출력 manifest와 같은 이름: run_id·revision·model_hash·pack·pack_version)
2. 전체 관계 개요: 속성 없이 엔티티와 관계만
3. 업무 영역별 상세도: 키 속성(PK·FK·UK)만, 좌우 배치. 인쇄 글자가 6pt보다 작으면 경고
4. 테이블 정의서: 전체 속성. 긴 표는 쪽마다 머리글 반복

보안 (ADR-0004 「Mermaid 설정 보안」, #190 R1 리뷰):
- Mermaid에는 이 모듈이 정한 설정만 넘기고 `secure` 목록으로 원문 지시문이 설정을 못 바꾸게 한다.
  원문 이름의 지시문 기호는 ERD 생성 코드(`codegen/erd.py` `_alias`)가 먼저 걸러 낸다.
- SVG는 `<img>`의 data URI로 넣는다. 이미지 안의 CSS·스크립트는 문서의 다른 요소에 닿지 않는다.
- PDF 변환은 `data:` 외의 주소(http·https·file 등)를 하나도 가져오지 않는다.

초안 표식: `draft=True`면 쪽마다 「초안 · 승인 전 · revision N」과 배경 표식을 넣는다.
사용자에게 주는 최종 PDF는 승인한 revision으로만 만든다 (docs/06, 호출·저장은 #17 R1).

이 모듈은 LLM client를 import하지 않는다 (CLAUDE.md). WeasyPrint는 Windows에서 GTK가 따로 있어야
import되므로 PDF로 바꿀 때만 불러온다.
"""

import base64
import html
import json
import logging
import re
import subprocess
import tempfile
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from specton.codegen.erd import render_erd
from specton.codegen.erd_areas import ErdArea, assign_areas, render_area_erd
from specton.contracts.design import Relationship
from specton.contracts.normalized import Column, NormalizedModel, Table

# ── 쪽·글자 기준 (ADR-0004 실측) ──────────────────────────

PAGE_WIDE_MM = (297.0, 210.0)  # 가로 용지 (너비, 높이)
MARGIN_MM = 12.0
TITLE_MM = 14.0  # 그림 위 제목 자리
MIN_PRINT_PT = 6.0  # 이보다 작으면 인쇄해 읽기 어렵다
MERMAID_TEXT_PX = 16  # Mermaid ER 기본 글자
PX_MM = 25.4 / 96
MAX_TABLE_COLUMNS = 20  # 넓은 표: 기준 열 + 20열까지 한 표 (ADR-0004)

# 표지 칸: #14 출력 manifest와 같은 이름·표시 이름 (R3 합의, 2026-11-08)
COVER_FIELDS: tuple[tuple[str, str], ...] = (
    ("run_id", "실행 ID"),
    ("revision", "리비전"),
    ("model_hash", "모델 해시"),
    ("pack", "도메인 팩"),
    ("pack_version", "팩 버전"),
)

# ── Mermaid (mermaid-cli 11.15.0) ─────────────────────────

FONT_FAMILY = '"Noto Sans CJK KR", "Noto Sans KR", sans-serif'

# 원문 지시문(`%%{init: ...}%%`)으로 바꿀 수 없게 막는 설정 키 (#190 R1 리뷰, Mermaid 보안 권고)
MERMAID_SECURE_KEYS: tuple[str, ...] = (
    "secure",
    "securityLevel",
    "startOnLoad",
    "maxTextSize",
    "maxEdges",
    "theme",
    "themeCSS",
    "themeVariables",
    "fontFamily",
    "altFontFamily",
    "htmlLabels",
    "dompurifyConfig",
)

# 개발자가 정한 설정만 넘긴다. 사용자 입력은 여기에 섞지 않는다.
MERMAID_CONFIG: dict[str, Any] = {
    "securityLevel": "strict",
    "secure": list(MERMAID_SECURE_KEYS),
    "theme": "neutral",
    "fontFamily": FONT_FAMILY,
    # HTML 조각(foreignObject) 대신 SVG 글자로 그린다. WeasyPrint는 SVG 이미지 안의 HTML을 그리지
    # 못해 상자 안 글자가 사라진다 (실제 렌더링에서 확인). HTML을 넣지 않으니 보안에도 낫다.
    "htmlLabels": False,
    "er": {"useMaxWidth": False},
}

MermaidRenderer = Callable[[str], str]
"""Mermaid 원문 → SVG 글자. 기본은 `MermaidCli`, 테스트는 가짜를 넘긴다."""


class PdfError(RuntimeError):
    """PDF를 만들지 못했다 (Mermaid 실패, PDF 변환 실패)."""


@dataclass(frozen=True)
class MermaidCli:
    """mermaid-cli(`mmdc`)로 SVG를 그린다.

    실행 이미지에 Node·mermaid-cli 11.15.0이 있어야 한다 (#25).

    `command`는 `mmdc` 실행 경로, `puppeteer_config`는 컨테이너에서 Chromium을 띄울 설정 파일이다.
    """

    command: tuple[str, ...] = ("mmdc",)
    puppeteer_config: Path | None = None
    timeout_seconds: float = 120.0

    def __call__(self, source: str) -> str:
        with tempfile.TemporaryDirectory(prefix="specton-erd-") as tmp:
            folder = Path(tmp)
            src, out, config = folder / "erd.mmd", folder / "erd.svg", folder / "mermaid.json"
            src.write_text(source, encoding="utf-8")
            config.write_text(json.dumps(MERMAID_CONFIG), encoding="utf-8")
            args = [*self.command, "-i", str(src), "-o", str(out), "-c", str(config), "-b", "white"]
            if self.puppeteer_config is not None:
                args += ["-p", str(self.puppeteer_config)]
            try:
                subprocess.run(args, check=True, capture_output=True, timeout=self.timeout_seconds)
            except (OSError, subprocess.SubprocessError) as exc:
                raise PdfError(f"Mermaid로 ERD를 그리지 못했습니다: {exc}") from exc
            if not out.is_file():
                raise PdfError("Mermaid가 SVG를 만들지 않았습니다")
            return out.read_text(encoding="utf-8")


# ── 그림 크기 ─────────────────────────────────────────────


def svg_size(svg: str) -> tuple[float, float]:
    """SVG의 원래 크기(px, viewBox)."""
    match = re.search(r'viewBox="([^"]+)"', svg)
    if not match:
        raise PdfError("SVG에 viewBox가 없습니다")
    try:
        parts = [float(v) for v in match.group(1).replace(",", " ").split()]
    except ValueError:
        parts = []
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise PdfError(f"SVG viewBox를 읽지 못했습니다: {match.group(1)}")
    return parts[2], parts[3]


@dataclass(frozen=True)
class Fit:
    """가로 용지에 넣은 그림 크기와 인쇄 글자 크기. 원래 크기보다 키우지 않는다."""

    width_mm: float
    height_mm: float
    text_pt: float


def fit_wide(svg: str) -> Fit:
    width, height = svg_size(svg)
    box_w = PAGE_WIDE_MM[0] - 2 * MARGIN_MM
    box_h = PAGE_WIDE_MM[1] - 2 * MARGIN_MM - TITLE_MM
    scale = min(box_w / (width * PX_MM), box_h / (height * PX_MM), 1.0)
    return Fit(
        width_mm=round(width * PX_MM * scale, 2),
        height_mm=round(height * PX_MM * scale, 2),
        text_pt=round(MERMAID_TEXT_PX * 0.75 * scale, 1),
    )


# ── 넓은 표 나누기 ────────────────────────────────────────


def split_columns(
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    keep: int = 1,
    width: int = MAX_TABLE_COLUMNS,
) -> list[tuple[list[str], list[list[str]]]]:
    """앞 `keep`열(예: 기능 ID)을 남기고 나머지 열을 `width`개씩 나눈 표들 (ADR-0004 넓은 표).

    `keep + width`열 이하면 표 하나 그대로다. 글자를 줄여 맞추지 않는다.
    """
    if keep < 0 or width < 1:
        raise ValueError("keep은 0 이상, width는 1 이상이어야 합니다")
    rest = len(header) - keep
    if rest <= width:
        return [(list(header), [list(r) for r in rows])]
    parts = []
    for start in range(keep, len(header), width):
        cols = [*range(keep), *range(start, min(start + width, len(header)))]
        parts.append(([header[c] for c in cols], [[r[c] for c in cols] for r in rows]))
    return parts


# ── 문서 조립 (HTML) ──────────────────────────────────────


@dataclass(frozen=True)
class CoverInfo:
    """표지 정보. 이름은 #14 출력 manifest·API와 같다."""

    run_id: str
    revision: int
    model_hash: str
    pack: str
    pack_version: str
    title: str = "ERD"


@dataclass(frozen=True)
class ErdFigure:
    """PDF에 넣을 그림 하나: 제목, Mermaid 원문, 그린 SVG, 크기."""

    kind: str  # "overview" | "area"
    title: str
    source: str
    svg: str
    fit: Fit


@dataclass(frozen=True)
class ErdDocument:
    """PDF로 바꾸기 전의 문서. 경고는 사람이 영역 낱말을 고칠 때 본다."""

    html: str
    figures: tuple[ErdFigure, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PdfResult:
    pdf: bytes
    pages: tuple[tuple[float, float], ...]  # 쪽마다 (너비, 높이) pt
    warnings: tuple[str, ...]
    blocked_urls: tuple[str, ...] = field(default=())


def erd_sources(
    model: NormalizedModel, relationships: Sequence[Relationship], areas: Sequence[ErdArea]
) -> list[tuple[str, str, str]]:
    """(종류, 제목, Mermaid 원문) 목록: 전체 관계 개요 → 영역별 상세도(키 속성만, 좌우 배치).

    팩에 영역이 없으면 모든 테이블이 「기타」 하나에 들어가 상세도가 한 장이다.
    """
    sources = [("overview", "전체 관계 개요", render_erd(model, relationships, attributes=False))]
    split = assign_areas(model.tables, areas)
    for area, table_ids in split.areas:
        title = f"영역 상세 · {area} ({len(table_ids)}개)"
        source = render_area_erd(model, relationships, split, area, keys_only=True, direction="LR")
        sources.append(("area", title, source))
    return sources


def build_erd_document(
    model: NormalizedModel,
    relationships: Sequence[Relationship],
    areas: Sequence[ErdArea],
    cover: CoverInfo,
    *,
    draft: bool,
    mermaid: MermaidRenderer,
) -> ErdDocument:
    """ERD PDF의 HTML. Mermaid로 그림을 그리고 상세도 글자 크기를 잰다."""
    figures = []
    warnings = []
    for kind, title, source in erd_sources(model, relationships, areas):
        svg = mermaid(source)
        fit = fit_wide(svg)
        figures.append(ErdFigure(kind=kind, title=title, source=source, svg=svg, fit=fit))
        if kind == "area" and fit.text_pt < MIN_PRINT_PT:
            warnings.append(
                f"{title}: 인쇄 글자가 {fit.text_pt}pt로 {MIN_PRINT_PT:g}pt보다 작습니다. "
                "영역 낱말을 나눠 상자 수를 줄여 주세요."
            )
    body = [
        _cover_html(cover, draft),
        *(_figure_html(f) for f in figures),
        _table_definition_html(model, areas),
    ]
    page = _page_html(title=f"Specton {cover.title}", body="".join(body), cover=cover, draft=draft)
    return ErdDocument(html=page, figures=tuple(figures), warnings=tuple(warnings))


_CSS = """
@page { size: A4; margin: 15mm 12mm 14mm;
  @top-left { content: string(doc); font-size: 8pt; color: #666; }
  @top-right { content: MARK; font-size: 8pt; color: #c2540a; }
  @bottom-center { content: counter(page) " / " counter(pages); font-size: 8pt; color: #666; } }
@page wide { size: A4 landscape; margin: 12mm 12mm 12mm;
  @top-left { content: string(doc); font-size: 8pt; color: #666; }
  @top-right { content: MARK; font-size: 8pt; color: #c2540a; } }
html { font-family: FONT; font-size: 9.5pt; color: #1d1d1f; }
h1 { string-set: doc content(); font-size: 18pt; margin: 0 0 6mm; }
h2 { font-size: 12pt; margin: 0 0 3mm; break-after: avoid; }
.draft-stamp { position: fixed; top: 95mm; left: 20mm; width: 100%; transform: rotate(-30deg);
  font-size: 80pt; font-weight: 700; color: rgba(243, 115, 33, .12); z-index: -1; }
.wide { page: wide; break-before: page; }
.figure img { display: block; margin: 0 auto; }
.portrait { break-before: page; }
table { border-collapse: collapse; width: 100%; }
th, td { border: .4pt solid #999; padding: 1.2mm 1.6mm; vertical-align: top; text-align: left; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { background: #fff1e8; }
.meta { width: auto; }
.meta th { width: 30mm; }
""".replace("FONT", FONT_FAMILY)


def _page_html(*, title: str, body: str, cover: CoverInfo, draft: bool) -> str:
    revision = f"revision {cover.revision}"
    mark = f"초안 · 승인 전 · {revision}" if draft else f"승인본 · {revision}"
    stamp = '<div class="draft-stamp">초안</div>' if draft else ""
    # 머리 표식은 쪽 여백 상자(@top-right)에 글자로 넣는다. 숨긴 요소의 string-set은 값을 넘기지
    # 않아 표식이 사라졌다 (실제 렌더링에서 확인).
    css = _CSS.replace("MARK", _css_string(mark))
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f"<title>{_esc(title)}</title><style>{css}</style></head><body>"
        f"{stamp}{body}</body></html>"
    )


def _css_string(text: str) -> str:
    """CSS 따옴표 문자열. 표식은 코드가 만든 글자지만 따옴표·역슬래시·줄바꿈은 걸러 둔다."""
    cleaned = "".join(" " if ch in "\r\n\f" else ch for ch in text)
    escaped = cleaned.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _cover_html(cover: CoverInfo, draft: bool) -> str:
    rows = "".join(
        f"<tr><th>{_esc(label)}</th><td>{_esc(str(getattr(cover, name)))}</td></tr>"
        for name, label in COVER_FIELDS
    )
    state = "초안 (승인 전)" if draft else "승인본"
    return (
        f"<section><h1>Specton {_esc(cover.title)}</h1>"
        f'<table class="meta"><tbody>{rows}<tr><th>상태</th><td>{state}</td></tr></tbody></table>'
        "</section>"
    )


def _figure_html(figure: ErdFigure) -> str:
    data = base64.b64encode(figure.svg.encode("utf-8")).decode("ascii")
    fit = figure.fit
    caption = f"{figure.title} · 글자 {fit.text_pt}pt"
    return (
        f'<section class="wide figure" data-kind="{figure.kind}"><h2>{_esc(caption)}</h2>'
        f'<img alt="{_esc(figure.title)}" src="data:image/svg+xml;base64,{data}" '
        f'style="width:{fit.width_mm}mm;height:{fit.height_mm}mm"></section>'
    )


TABLE_HEADER = ("테이블", "테이블 물리명", "컬럼", "컬럼 물리명", "타입", "키", "NULL")


def table_definition_rows(model: NormalizedModel, areas: Sequence[ErdArea]) -> list[list[str]]:
    """테이블 정의서 행: 영역 순서대로 테이블마다 모든 컬럼 (상세도에 없는 속성까지)."""
    split = assign_areas(model.tables, areas)
    by_id = {t.id: t for t in model.tables}
    fk_columns = {c for fk in model.foreign_keys for c in fk.columns}
    rows: list[list[str]] = []
    for _, table_ids in split.areas:
        for tid in table_ids:
            table = by_id[tid]
            rows.extend(_column_row(table, col, fk_columns) for col in table.columns)
    return rows


def _column_row(table: Table, col: Column, fk_columns: set[str]) -> list[str]:
    keys = [
        key
        for key, applies in (
            ("PK", col.id in table.primary_key),
            ("FK", col.id in fk_columns),
            ("UK", any(col.id in unique for unique in table.unique_keys)),
        )
        if applies
    ]
    return [
        table.name,
        table.physical_name,
        col.name,
        col.physical_name,
        _type_text(col),
        ",".join(keys),
        "Y" if col.nullable else "N",
    ]


def _type_text(col: Column) -> str:
    base = col.data_type.value
    if col.length is not None:
        return f"{base}({col.length})"
    if col.time_precision is not None:
        return f"{base}({col.time_precision})"
    if col.precision is not None:
        scale = f",{col.scale}" if col.scale is not None else ""
        return f"{base}({col.precision}{scale})"
    return base


def _table_definition_html(model: NormalizedModel, areas: Sequence[ErdArea]) -> str:
    return (
        '<section class="portrait"><h2>테이블 정의서</h2>'
        + table_html(TABLE_HEADER, table_definition_rows(model, areas))
        + "</section>"
    )


def table_html(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """머리글이 쪽마다 반복되는 표 (`thead`). 글자는 모두 HTML로 이스케이프한다."""
    head = "".join(f"<th>{_esc(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


# ── PDF 변환 (WeasyPrint) ─────────────────────────────────


class _MissingGlyphs(logging.Handler):
    """WeasyPrint가 폰트에 없는 글자를 □(.notdef)로 그렸다는 경고를, 그 경고를 낸 스레드에서
    지금 렌더링 중인 `html_to_pdf` 호출(`collect`)에 넘긴다.

    `weasyprint` 로거는 프로세스 전체가 함께 쓴다. 실행기가 PDF 여러 개를 동시에 만들 때
    (`run_concurrency`) 경고가 섞이거나 빠지지 않게 두 가지를 지킨다 (#209 R1 리뷰).
    - 경고는 그것을 낸 스레드의 렌더링에만 넘긴다. WeasyPrint의 `render`·`write_pdf`는
      부른 스레드에서 그대로 돈다.
    - 핸들러는 로거에 한 번만 걸고 떼지 않는다(`_glyph_watch`). 호출마다 붙였다 떼면
      다른 스레드가 핸들러 목록을 도는 중에 목록이 바뀌어 그 스레드의 핸들러를 건너뛰고,
      깨진 PDF가 성공으로 나온다.
    """

    _PATTERN = re.compile(
        r"\.notdef glyph rendered for Unicode string unsupported by fonts: " r'"(.*)"'
    )

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self._local = threading.local()

    @contextmanager
    def collect(self) -> Iterator[set[str]]:
        """이 스레드에서 블록 안에 나온 깨진 글자를 모은 집합."""
        chars: set[str] = set()
        previous = getattr(self._local, "chars", None)
        self._local.chars = chars
        try:
            yield chars
        finally:
            self._local.chars = previous

    def emit(self, record: logging.LogRecord) -> None:
        chars = getattr(self._local, "chars", None)
        if chars is None:
            return  # 이 스레드는 지금 렌더링 중이 아니다 (다른 렌더링의 경고)
        match = self._PATTERN.search(record.getMessage())
        if match:
            chars.update(match.group(1))


_GLYPHS = _MissingGlyphs()
_GLYPHS_LOCK = threading.Lock()


def _glyph_watch() -> _MissingGlyphs:
    """상시 핸들러를 `weasyprint` 로거에 한 번만 건다. 렌더링마다 핸들러 목록을 바꾸지 않는다."""
    logger = logging.getLogger("weasyprint")
    with _GLYPHS_LOCK:
        if _GLYPHS not in logger.handlers:
            logger.addHandler(_GLYPHS)
    return _GLYPHS


def html_to_pdf(document: str) -> PdfResult:
    """HTML → PDF. `data:` 외의 주소는 가져오지 않고 막은 주소를 돌려준다.

    폰트에 없는 글자가 있으면(한글 폰트 미설치 등) 깨진 PDF를 내지 않고 `PdfError`로 멈춘다.
    """
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
        from weasyprint.urls import URLFetcher  # type: ignore[import-untyped]
    except (ImportError, OSError) as exc:  # Windows에서 GTK가 없으면 OSError
        raise PdfError(f"WeasyPrint를 불러오지 못했습니다: {exc}") from exc

    blocked: list[str] = []

    class _DataOnly(URLFetcher):  # type: ignore[misc]
        """엔진이 직접 넣은 data URI만 허용한다 (ADR-0004 외부 URL·임의 파일 차단)."""

        def fetch(self, url: str, headers: Any = None) -> Any:
            if not url.lower().startswith("data:"):
                blocked.append(url)
                raise ValueError(f"외부 리소스를 가져오지 않습니다: {url}")
            return super().fetch(url, headers)

    with _glyph_watch().collect() as missing:
        try:
            fetcher = _DataOnly(allowed_protocols={"data"})
            rendered = HTML(string=document, url_fetcher=fetcher).render()
            pdf = rendered.write_pdf()
        except Exception as exc:  # WeasyPrint 내부 오류를 PDF 오류 하나로
            raise PdfError(f"PDF로 바꾸지 못했습니다: {exc}") from exc
    if missing:
        # 폰트에 없는 글자는 □로 깨진 채 PDF가 나온다. 조용히 넘기지 않는다 (실행 이미지 #25 점검).
        sample = "".join(sorted(missing)[:10])
        raise PdfError(
            f"폰트에 없는 글자가 있어 PDF 글자가 깨집니다: {sample} "
            "(한글 폰트 fonts-noto-cjk가 설치돼 있는지 확인하세요)"
        )
    if not isinstance(pdf, bytes):
        raise PdfError("PDF 바이트를 받지 못했습니다")
    pages = tuple((float(p.width), float(p.height)) for p in rendered.pages)
    return PdfResult(pdf=pdf, pages=pages, warnings=(), blocked_urls=tuple(blocked))


def render_erd_pdf(
    model: NormalizedModel,
    relationships: Sequence[Relationship],
    areas: Sequence[ErdArea],
    cover: CoverInfo,
    *,
    draft: bool,
    mermaid: MermaidRenderer | None = None,
) -> PdfResult:
    """ERD PDF 바이트. 호출·저장·승인본 게시는 실행 흐름(#17)이 맡는다."""
    document = build_erd_document(
        model, relationships, areas, cover, draft=draft, mermaid=mermaid or MermaidCli()
    )
    result = html_to_pdf(document.html)
    return PdfResult(
        pdf=result.pdf,
        pages=result.pages,
        warnings=document.warnings,
        blocked_urls=result.blocked_urls,
    )
