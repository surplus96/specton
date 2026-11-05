"""#10 표 파서 결과가 source_block에 그대로 저장되는지 (빈 행·여러 줄 판정 이유)."""

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest

from specton.contracts import DesignState
from specton.ingest.tabular import read_csv
from specton.persistence import lease
from specton.persistence.db import Pool
from specton.persistence.runs import add_document, create_run
from specton.persistence.snapshots import save_model

pytestmark = pytest.mark.db


def test_parsed_blocks_keep_empty_text_and_multiline_notice(
    pool: Pool, sample_state: Callable[[str, str], DesignState], tmp_path: Path
) -> None:
    """빈 행(source_text 없음)과 줄바꿈으로 이은 notice가 저장 뒤에도 같다."""
    path = tmp_path / "req.csv"
    path.write_text(  # 머리글 바로 아래 ID 없는 행은 2단 머리글로 읽히므로 정상 행을 먼저 둔다
        "요구사항 ID,구분,요구사항명,상세 내용\n"
        "INV-001,기능,입고,입고 등록\n,기능,출고,\nINV-002,범례,,\n",
        encoding="utf-8",
    )
    with pool.connection() as conn:
        run = create_run(conn, "owner-a", "inventory")
        document_id = uuid4()
        add_document(
            conn, run.run_id, document_id=document_id, file_name="req.csv",
            file_format="csv", file_hash="h", storage_ref="x",
        )  # fmt: skip
        assert lease.acquire(conn, run.run_id, "w1", 60)
        blocks = read_csv(path, str(document_id)).requirements
        state = sample_state(str(run.run_id), str(document_id))
        save_model(conn, run.run_id, "w1", state.evolve(source_requirements=blocks))
        rows = conn.execute(
            "SELECT block_id, source_text, notice FROM source_block ORDER BY block_id"
        ).fetchall()

    assert [tuple(r.values()) for r in rows] == [
        (b.block_id, b.source_text, b.notice) for b in blocks
    ]
    assert rows[0]["notice"] is None
    assert (
        rows[1]["notice"]
        == "요구사항 ID 없음\n요구사항 세부내용이 없어 요구사항명을 원문 문장으로 씀"
    )
    assert rows[2]["source_text"] is None
