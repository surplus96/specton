"""문서 읽기(parse) 노드 (#17, ADR-0015 결정 3). 통합 담당(R1)만 수정한다.

- 실행기가 첫 상태의 `documents`에 넣은 업로드 문서를 형식별 파서(`specton/ingest/`)로 읽어
  `DesignState.source_requirements`에 둔다. 판정(`pass`·`review`·`fail`)은 파서가 정한다.
- 파일 단위로 읽지 못하면(`UnsupportedInput`) `ExtractionFailedError`로 실행을 끝낸다.
- HWPX 파서는 #24에서 만든다. 그때까지 HWPX는 읽지 못한 파일로 끝낸다.
- 요구사항명·상세 내용이 모두 빈 행은 파서가 원문 문장 없는 `review` 블록으로 돌려준다(#10).
  `ExtractionIssue`는 지금 표 파서가 만들지 않지만 오면 로그에 남긴다.
  건너뛴 시트는 지금 로그에만 남기고, 화면에 보일 자리는 #19와 정한다.
"""

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from specton.contracts.requirements import SourceRequirement
from specton.graph import DocumentRef, ExtractionFailedError, GraphState, Node
from specton.ingest.tabular import TabularResult, UnsupportedInput, read_csv, read_excel

logger = logging.getLogger(__name__)

_READERS: Mapping[str, Callable[[Path, str], TabularResult]] = {
    "xlsx": read_excel,
    "csv": read_csv,
}


def parse_node(storage_dir: Path) -> Node:
    """parse 노드. 문서 위치는 `storage_dir` 기준 상대 경로(`storage_ref`)로 받는다."""

    def parse(state: GraphState) -> Mapping[str, Any]:
        documents = state.get("documents", ())
        if not documents:
            raise ValueError("parse: 실행에 연결된 문서가 없습니다")
        blocks = tuple(b for doc in documents for b in _read(storage_dir, doc))
        if not blocks:
            raise ExtractionFailedError(
                "읽은 요구사항이 없어요. 요구사항명이나 상세 내용을 적은 뒤 다시 올려 주세요.",
                "원문 블록이 0건입니다 (원문을 만들지 못한 행만 있음)",
            )
        return {"design": state["design"].evolve(source_requirements=blocks)}

    return parse


def _read(storage_dir: Path, doc: DocumentRef) -> tuple[SourceRequirement, ...]:
    reader = _READERS.get(doc["file_format"])
    if reader is None:
        raise ExtractionFailedError(
            "아직 읽을 수 없는 형식이에요. 엑셀(.xlsx)이나 CSV로 올려 주세요.",
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
    if result.skipped_sheets:
        logger.info("문서 %s: 건너뛴 시트 %s", doc["document_id"], list(result.skipped_sheets))
    return result.requirements
