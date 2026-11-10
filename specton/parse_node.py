"""문서 읽기(parse) 노드 (#17, ADR-0015 결정 3). 통합 담당(R1)만 수정한다.

- 실행기가 첫 상태의 `documents`에 넣은 업로드 문서를 형식별 파서(`specton/ingest/`)로 읽어
  `DesignState.source_requirements`에 둔다. 판정(`pass`·`review`·`fail`)은 파서가 정한다.
- 파일 단위로 읽지 못하면(`UnsupportedInput`) `ExtractionFailedError`로 실행을 끝낸다.
- 한글(.hwp·.hwpx)은 요구사항 상세표를 읽는 `read_hangul`(#24)로 읽는다. .hwp도 변환하지 않는다.
- 요구사항명·상세 내용이 모두 빈 행은 파서가 원문 문장 없는 `review` 블록으로 돌려준다(#10).
  `ExtractionIssue`는 지금 표 파서가 만들지 않지만 오면 로그에 남긴다.
- 건너뛴 시트(요구사항 표가 없거나 빈 표)는 확인·제외 대상이 아니라 안내 한 줄이다 (#95 결론,
  docs/09 UI-02). 문서마다 `notes`로 돌려주고 실행기가 status 이벤트로 기록한다.
"""

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from specton.graph import DocumentRef, ExtractionFailedError, GraphState, Node, RunNote
from specton.ingest.hangul import read_hangul
from specton.ingest.tabular import TabularResult, UnsupportedInput, read_csv, read_excel

logger = logging.getLogger(__name__)

_READERS: Mapping[str, Callable[[Path, str], TabularResult]] = {
    "xlsx": read_excel,
    "csv": read_csv,
    "hwp": read_hangul,
    "hwpx": read_hangul,
}


def parse_node(storage_dir: Path) -> Node:
    """parse 노드. 문서 위치는 `storage_dir` 기준 상대 경로(`storage_ref`)로 받는다."""

    def parse(state: GraphState) -> Mapping[str, Any]:
        documents = state.get("documents", ())
        if not documents:
            raise ValueError("parse: 실행에 연결된 문서가 없습니다")
        results = [(doc, _read(storage_dir, doc)) for doc in documents]
        blocks = tuple(b for _, result in results for b in result.requirements)
        if not blocks:
            raise ExtractionFailedError(
                "읽은 요구사항이 없어요. 요구사항명이나 상세 내용을 적은 뒤 다시 올려 주세요.",
                "원문 블록이 0건입니다 (원문을 만들지 못한 행만 있음)",
            )
        notes = tuple(
            _skipped_sheets(doc, result.skipped_sheets)
            for doc, result in results
            if result.skipped_sheets
        )
        return {"design": state["design"].evolve(source_requirements=blocks), "notes": notes}

    return parse


def _read(storage_dir: Path, doc: DocumentRef) -> TabularResult:
    reader = _READERS.get(doc["file_format"])
    if reader is None:
        raise ExtractionFailedError(
            "아직 읽을 수 없는 형식이에요. 엑셀(.xlsx)·CSV·한글(.hwpx·.hwp)로 올려 주세요.",
            f"{doc['file_format']} 파서가 아직 없습니다",
        )
    try:
        result = reader(storage_dir / doc["storage_ref"], doc["document_id"])
    except UnsupportedInput as exc:
        raise ExtractionFailedError(exc.notice, exc.detail) from exc
    for issue in result.issues:
        logger.warning(
            "문서 %s %s: 원문 블록으로 만들지 못한 행 (%s)",
            doc["document_id"],
            issue.source_ref.model_dump(exclude_none=True),
            issue.notice,
        )
    return result


def _skipped_sheets(doc: DocumentRef, sheets: tuple[str, ...]) -> RunNote:
    payload = {"info": "skipped_sheets", "document_id": doc["document_id"], "sheets": list(sheets)}
    return RunNote(message="요구사항을 읽지 않은 시트가 있습니다", payload=payload)
