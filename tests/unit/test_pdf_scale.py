"""20테이블 규모의 ERD PDF 실측 (#13, ADR-0004 「PDF 출력 실측」).

- 모델 크기 시험은 어디서나 돈다(LLM·DB·Mermaid 없음).
- PDF 시험은 한글 폰트·mermaid-cli가 있는 실행 이미지에서만 돈다(`docker build --target check`).
  `SPECTON_SCALE_REPORT=<경로>`를 주면 그림별 글자 크기 표를 Markdown으로 남긴다(ADR 실측 기록용).
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

import pytest
from erd_scale_model import build_scale_model
from test_pdf_engine import COVER, _weasyprint

from specton.codegen.erd_areas import OTHER_AREA, assign_areas
from specton.export.pdf import MIN_PRINT_PT, MermaidCli, build_erd_document, html_to_pdf, svg_size

# 그림 안 상자: `물리명["한글명"] {` 또는 다른 영역 참조 상자 `물리명["한글명 (→ 영역)"]`
_BOX = re.compile(r'^\s+[A-Za-z_]\w*\["', re.MULTILINE)

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


def test_scale_model_has_the_size_of_the_1108_measurement() -> None:
    """11/8 실측(테이블 20 · 컬럼 86 · FK 25 · 관계 24)과 같은 규모로 정리된다."""
    model, relationships, areas = build_scale_model()
    assert len(model.tables) == 20
    assert len(model.foreign_keys) == 25
    assert len(relationships) == 24
    assert 80 <= sum(len(t.columns) for t in model.tables) <= 95
    split = dict(assign_areas(model.tables, areas).areas)
    sizes = {name: len(ids) for name, ids in split.items() if ids}
    # 「단위」는 팩 영역 낱말에 없어 기타로 간다 (erd_areas.yaml 보완 후보)
    assert sizes == {"수불": 7, "재고 이력": 6, "기준정보": 6, OTHER_AREA: 1}


@pytest.mark.skipif(shutil.which("mmdc") is None, reason="mermaid-cli(mmdc)가 없는 환경")
def test_scale_erd_pdf_renders_every_figure() -> None:
    _weasyprint(korean=True)
    model, relationships, areas = build_scale_model()
    config = os.environ.get("SPECTON_MMDC_PUPPETEER")
    cli = MermaidCli(puppeteer_config=Path(config) if config else None)

    started = time.perf_counter()
    document = build_erd_document(model, relationships, areas, COVER, draft=True, mermaid=cli)
    drawn = time.perf_counter()
    result = html_to_pdf(document.html)
    written = time.perf_counter()

    assert result.pdf.startswith(b"%PDF-") and not result.blocked_urls
    overview = [f for f in document.figures if f.kind == "overview"]
    area_figures = [f for f in document.figures if f.kind == "area"]
    assert len(overview) == 1
    assert len(area_figures) == 4  # 수불 · 재고 이력 · 기준정보 · 기타
    assert all("<svg" in f.svg for f in document.figures)
    # 관계 이름이 다른 이름에 가려지지 않는다 (#261). 개요는 이름을 빼서 0개, 상세도는 이름이
    # 있고 겹치지 않는다. 이름을 넣은 개요에서는 창고·품목 → 창고재고의 REL-04·REL-05가 겹쳤다.
    assert _label_boxes(overview[0].svg) == []
    assert all(_label_boxes(f.svg) for f in area_figures)
    assert {f.title: _overlapping_labels(f.svg) for f in document.figures} == {
        f.title: [] for f in document.figures
    }
    # 이 모델은 품목·창고에 자식이 많아 개요가 넓어 6pt보다 작다(실측 4.5pt). 개요는 나누지 않고
    # 경고만 한다 (#236 R1 결정). 경고는 6pt 미만 그림마다 하나: 개요 + 기준정보 상세도.
    assert overview[0].fit.text_pt < MIN_PRINT_PT
    small = [f.title for f in document.figures if f.fit.text_pt < MIN_PRINT_PT]
    assert [w.split(":")[0] for w in document.warnings] == small
    assert small[0] == "전체 관계 개요" and any(t.startswith("영역 상세 · 기준정보") for t in small)

    report = os.environ.get("SPECTON_SCALE_REPORT")
    if report:
        landscape = sum(1 for w, h in result.pages if w > h)
        lines = [
            "| 그림 | 종류 | 상자 | SVG(px) | 인쇄 글자 |",
            "|---|---|---|---|---|",
            *(
                f"| {f.title} | {f.kind} | {len(_BOX.findall(f.source))} | "
                f"{svg_size(f.svg)[0]:.0f}x{svg_size(f.svg)[1]:.0f} | {f.fit.text_pt}pt |"
                for f in document.figures
            ),
            "",
            f"- 모델: 테이블 {len(model.tables)} · 컬럼 {sum(len(t.columns) for t in model.tables)}"
            f" · FK {len(model.foreign_keys)} · 관계 {len(relationships)}",
            f"- PDF: {len(result.pages)}쪽(가로 {landscape}"
            f" · 세로 {len(result.pages) - landscape}), {len(result.pdf) / 1024:.0f}KB",
            f"- 시간: Mermaid {len(document.figures)}개 {drawn - started:.1f}초,"
            f" HTML→PDF {written - drawn:.1f}초",
            *(f"- 경고: {w}" for w in document.warnings),
        ]
        Path(report).write_text("\n".join(lines) + "\n", encoding="utf-8")
