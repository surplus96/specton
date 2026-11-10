"""실제 두 PDF·8종 산출물 통합 시험의 API·파일·승인 근거 도우미."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from test_scripted_flow import _Flow

from specton.config import Settings
from specton.model_hash import model_hash
from specton.packs.provenance import policy_digest
from specton.persistence.db import Pool
from specton.persistence.validations import current_validation

OUTPUTS = {
    ("ddl", "sql"),
    ("erd", "mmd"),
    ("erd", "pdf"),
    ("functions", "md"),
    ("functions", "pdf"),
    ("rtm", "csv"),
    ("rtm", "xlsx"),
    ("manifest", "json"),
}
PRIVATE = {("erd", "pdf"), ("functions", "pdf"), ("manifest", "json")}


@dataclass
class World:
    pool: Pool
    settings: Settings
    flow: _Flow
    renders: list[tuple[str, int]]

    def respond(self, run_id: str, response: dict[str, Any]) -> dict[str, Any]:
        assert self.flow.resume(self.flow.status(run_id), response).status_code == 202
        self.flow.runner.run_pending()
        return self.flow.status(run_id)

    def review(self, run_id: str, decision: str) -> dict[str, Any]:
        return self.respond(
            run_id,
            {
                "kind": "review",
                "decision": decision,
                "feedback": "입고일자를 확인한다" if decision == "revise" else "",
            },
        )

    def start(self, *, restart_requirements: bool = False) -> str:
        run_id = self.flow.upload()
        self.flow.runner.run_pending()
        assert self.flow.status(run_id)["interrupt"]["kind"] == "extraction"
        status = self.respond(
            run_id,
            {
                "kind": "extraction",
                "confirmed": True,
                "excluded_blocks": [],
            },
        )
        assert status["interrupt"]["kind"] == "requirements"
        if restart_requirements:
            saved = self.flow.view(run_id, "requirements")
            self.restart()
            assert self.flow.status(run_id) == status
            assert self.flow.view(run_id, "requirements") == saved
        status = self.respond(
            run_id,
            {
                "kind": "requirements",
                "answers": [{"req_id": "REQ-01", "action": "keep", "texts": []}],
            },
        )
        assert status["status"] == "awaiting_review", status
        if restart_requirements:
            assert self.flow.transport.calls["A01"] == 0
        return run_id

    def restart(self) -> None:
        previous = self.flow
        previous.runner.stop()
        self.flow = _Flow(self.pool, self.settings)
        self.flow.client.cookies.update(previous.client.cookies)
        previous.client.close()

    def download(self, run_id: str, key: tuple[str, str], revision: int) -> Any:
        return self.flow.client.get(
            f"/runs/{run_id}/artifacts/{key[0]}",
            params={"file_format": key[1], "revision": revision},
        )

    def rows(self, run_id: str, revision: int) -> dict[tuple[str, str], dict[str, Any]]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT a.*,s.revision,s.model_hash FROM artifact a "
                "JOIN model_snapshot s USING(snapshot_id) WHERE s.run_id=%s AND s.revision=%s",
                (UUID(run_id), revision),
            ).fetchall()
        return {(r["kind"], r["file_format"]): r for r in rows}

    def candidates(self, run_id: str, revision: int) -> dict[tuple[str, str], bytes]:
        rows = self.rows(run_id, revision)
        assert set(rows) == OUTPUTS
        assert all(r["approval_status"] == "draft" for r in rows.values())
        content = {
            key: (self.settings.storage_dir / r["storage_ref"]).read_bytes()
            for key, r in rows.items()
        }
        assert all(hashlib.sha256(content[key]).hexdigest() == r["hash"] for key, r in rows.items())
        self.assert_provenance(run_id, revision, content)
        for key in OUTPUTS:
            response = self.download(run_id, key, revision)
            if key in PRIVATE:
                assert response.status_code == 409
            else:
                assert response.status_code == 200 and response.content == content[key]
                assert "-draft" in response.headers["content-disposition"]
        return content

    def assert_provenance(
        self,
        run_id: str,
        revision: int,
        content: dict[tuple[str, str], bytes],
    ) -> None:
        design = self.flow.runner.graph.get_state({"configurable": {"thread_id": run_id}}).values[
            "design"
        ]
        digest = model_hash(design)
        assert design.normalized is not None and design.revision == revision
        assert design.versions.pack_id == "inventory" and design.versions.pack_version == "0.1.21"
        assert design.normalized.common_version == "0.1.6"
        assert design.normalized.policy_digest == policy_digest(
            self.settings.pack_root, "inventory"
        )
        assert {r["model_hash"] for r in self.rows(run_id, revision).values()} == {digest}
        exported = json.loads(content[("manifest", "json")])
        assert exported["run_id"] == run_id and int(exported["revision"]) == revision
        assert exported["model_hash"] == digest and exported["approved"] is True
        assert exported["pack"] == "inventory" and exported["pack_version"] == "0.1.21"
        assert exported["source_hash"] == design.versions.document_hash
        assert exported["generator_versions"]["common_version"] == "0.1.6"
        assert exported["generator_versions"]["policy_digest"] == design.normalized.policy_digest
        files = {(f["kind"], f["file_format"]): f["hash"] for f in exported["files"]}
        assert set(files) == OUTPUTS - {("manifest", "json")}
        assert files == {k: hashlib.sha256(v).hexdigest() for k, v in content.items() if k in files}
        for key in (("erd", "pdf"), ("functions", "pdf")):
            assert content[key].startswith(b"%PDF-") and len(content[key]) > 1000
        assert content[("rtm", "xlsx")].startswith(b"PK")

    def assert_approved(
        self,
        run_id: str,
        revision: int,
        content: dict[tuple[str, str], bytes],
    ) -> None:
        assert self.review(run_id, "approve")["status"] == "completed"
        rows = self.rows(run_id, revision)
        assert all(row["approval_status"] == "approved" for row in rows.values())
        for key, expected in content.items():
            response = self.download(run_id, key, revision)
            assert response.status_code == 200 and response.content == expected
            assert "-draft" not in response.headers["content-disposition"]
        with self.pool.connection() as conn:
            basis = conn.execute(
                "SELECT a.kind,a.file_format,b.artifact_hash,b.validation_id FROM approval_basis b "
                "JOIN approval p USING(approval_id) JOIN artifact a USING(artifact_id) "
                "JOIN model_snapshot s ON a.snapshot_id=s.snapshot_id "
                "WHERE p.run_id=%s AND s.revision=%s",
                (UUID(run_id), revision),
            ).fetchall()
            validation = current_validation(conn, UUID(run_id), revision)
        assert len(basis) == 8
        assert {(b["kind"], b["file_format"], b["artifact_hash"]) for b in basis} == {
            (*key, hashlib.sha256(value).hexdigest()) for key, value in content.items()
        }
        assert validation is not None and validation.result.status == "passed"
        assert all((b["validation_id"] is not None) == (b["kind"] == "ddl") for b in basis)
        assert (
            validation.result.artifact_hash == hashlib.sha256(content[("ddl", "sql")]).hexdigest()
        )
