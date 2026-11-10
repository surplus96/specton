"""#290: 실제 PostgreSQL에서 복합 업무 UNIQUE와 재사용 FK 제약을 실행한다."""

import psycopg
import pytest

from specton.codegen.ddl import generate_ddl
from specton.codegen.model import Normalized
from specton.codegen.naming import NamingRules, PackLexicon
from specton.codegen.normalize import PackRef, normalize
from specton.contracts import DesignState
from specton.persistence.db import Pool

pytestmark = pytest.mark.db


def test_postgres_preserves_business_unique_without_global_component_uniqueness(pool: Pool) -> None:
    def attribute(id: str, name: str, *, key: bool = False) -> dict[str, object]:
        return {
            "id": id,
            "name": name,
            "data_type": "varchar",
            "length": 10,
            "is_key": key,
            "nullable": False,
            "req_ids": ["REQ-01"],
        }

    state = DesignState.model_validate(
        {
            "run_id": "synthetic-keys",
            "requirements": [
                {
                    "id": "REQ-01",
                    "source_ref": {"file_format": "csv", "row": 2},
                    "text": "부모별 구분번호는 중복되지 않는다",
                    "draft_text": "합성 문장",
                    "type": "FR",
                    "analysis_version": 1,
                }
            ],
            "entities": [
                {
                    "id": "ENT-P",
                    "pack": "inventory",
                    "name": "부모",
                    "description": "합성 부모",
                    "req_ids": ["REQ-01"],
                    "attributes": [attribute("A-P", "식별번호", key=True)],
                },
                {
                    "id": "ENT-C",
                    "pack": "inventory",
                    "name": "자식",
                    "description": "합성 자식",
                    "req_ids": ["REQ-01"],
                    "attributes": [
                        attribute("A-C", "식별번호", key=True),
                        attribute("A-CP", "부모번호"),
                        attribute("A-S", "구분번호"),
                    ],
                    "unique_keys": [["A-CP", "A-S"]],
                },
            ],
            "relationships": [
                {
                    "id": "REL-01",
                    "parent": "ENT-P",
                    "child": "ENT-C",
                    "cardinality": "1:N",
                    "optional": False,
                    "rationale": "부모에 속함",
                    "req_ids": ["REQ-01"],
                    "fk_bindings": [{"parent_attribute_id": "A-P", "child_attribute_id": "A-CP"}],
                }
            ],
        }
    )
    rules = NamingRules(max_bytes=63, reserved_words=frozenset())
    lexicon = PackLexicon(
        terms={},
        tokens={
            "부모": "PARENT",
            "자식": "CHILD",
            "식별번호": "ID_NO",
            "부모번호": "PARENT_NO",
            "구분번호": "SEQ_NO",
        },
        separator="_",
        digest="synthetic",
    )
    result = normalize(state, pack=PackRef("inventory", "test"), lexicon=lexicon, rules=rules)
    assert isinstance(result, Normalized), result
    with pool.connection() as conn:
        conn.execute(generate_ddl(result.model, max_bytes=63).sql, prepare=False)
        conn.execute("INSERT INTO parent VALUES ('P1'), ('P2')")
        conn.execute(
            "INSERT INTO child (id_no,parent_no,seq_no) VALUES ('C1','P1','1'),('C2','P2','1')"
        )
        with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
            conn.execute("INSERT INTO child (id_no,parent_no,seq_no) VALUES ('C3','P1','1')")
        with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
            conn.execute("INSERT INTO child (id_no,parent_no,seq_no) VALUES ('C4','missing','2')")
        assert conn.execute("SELECT count(*) FROM child").fetchone()["count"] == 2
