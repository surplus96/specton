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
    # 개요 글자 크기는 모델 모양(한 테이블에 달린 자식 수)에 따라 달라 기준을 두지 않고 기록만 한다.
    # 6pt 경고는 상세도에만 있다 (ADR-0004). 이 모델은 품목·창고에 자식이 많아 개요가 넓다.
    assert len(overview) == 1 and overview[0].fit.text_pt > 0
    assert len(area_figures) == 4  # 수불 · 재고 이력 · 기준정보 · 기타
    assert all("<svg" in f.svg for f in document.figures)
    small = [f.title for f in area_figures if f.fit.text_pt < MIN_PRINT_PT]
    assert len(document.warnings) == len(small)  # 6pt 미만 상세도마다 경고 하나

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
