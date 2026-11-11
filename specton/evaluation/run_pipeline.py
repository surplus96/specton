"""python -m specton.evaluation.run_pipeline: 고정 조건으로 실제 API 전체 실행·기록."""

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from openai import OpenAI
from psycopg import sql

from specton.api.main import create_app
from specton.config import Settings
from specton.evaluation.pipeline import ACTIVE_RUN, create_evaluation_graph, load_condition
from specton.llm.client import LLMClient
from specton.llm.errors import LLMBudgetExceededError
from specton.llm.openai_transport import OpenAITransport
from specton.model_hash import model_hash
from specton.persistence.db import apply_schema, create_checkpointer, create_pool
from specton.runner import Runner

# 고정 추정 단가: OpenAI 공식 모델 페이지 2026-11-10 확인. 청구서 금액이 아니다.
RATES = {"gpt-6.1-sol": (2.0, 0.1, 2.5, 10.0), "gpt-6-luna": (0.1, 0.01, 0.125, 0.5)}


def write(path: Path, data: object) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )


def metered_client(
    settings: Settings,
    output: Path,
    ledger: list[dict[str, Any]],
    *,
    previous_usd: float,
    allocation: float,
) -> LLMClient:
    if settings.openai_api_key is None or not settings.openai_api_key.get_secret_value().strip():
        raise ValueError("실제 실행 API 키가 설정되지 않았습니다")
    sdk = OpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_api_retries,
    )
    original = sdk.responses.create
    local = threading.local()
    lock = threading.Lock()

    def record(*args: Any, **kwargs: Any) -> Any:
        with lock:
            if previous_usd + sum(r.get("estimated_usd") or 0 for r in ledger) >= allocation:
                raise LLMBudgetExceededError("평가 지출 기준에 도달했습니다")
        start = time.monotonic()
        row: dict[str, Any] = {
            "stage": getattr(local, "stage", None),
            "run_id": ACTIVE_RUN.get(),
            "model": kwargs.get("model"),
            "started_at": time.time(),
            "estimated_usd": None,
            "sdk_retry_count": None,
        }
        try:
            response = original(*args, **kwargs)
            usage = response.usage.model_dump() if response.usage else None
            row.update(response_id=response.id, usage=usage, status="returned")
            if usage and kwargs["model"] in RATES:
                inp = usage["input_tokens"]
                out = usage["output_tokens"]
                detail = usage.get("input_tokens_details") or {}
                cached = detail.get("cached_tokens", 0) or 0
                writes = detail.get("cache_write_tokens", 0) or 0
                a, b, w, c = RATES[kwargs["model"]]
                long = inp > 272000
                row["estimated_usd"] = (
                    (inp - cached - writes) * a * (2 if long else 1)
                    + cached * b * (2 if long else 1)
                    + writes * w * (2 if long else 1)
                    + out * c * (1.5 if long else 1)
                ) / 1_000_000
            return response
        except Exception as exc:
            row.update(status="error", error_type=type(exc).__name__)
            raise
        finally:
            row["duration_ms"] = round((time.monotonic() - start) * 1000)
            with lock:
                ledger.append(row)
                with (output / "calls.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")

    sdk.responses.create = record  # type: ignore[method-assign]

    class Metered(OpenAITransport):
        def send(self, request: Any, output_model: Any) -> Any:
            local.stage = request.stage
            return super().send(request, output_model)

    return LLMClient(Metered(sdk), max_structured_retries=settings.max_structured_retries)


def execute(
    condition_path: Path,
    settings: Settings,
    output: Path,
    *,
    previous_usd: float = 0,
    allocation: float = 100,
) -> dict[str, Any]:
    if (
        not all(math.isfinite(v) for v in (previous_usd, allocation))
        or previous_usd < 0
        or allocation <= 0
    ):
        raise ValueError("지출 기준은 유한한 양수여야 합니다")
    condition = load_condition(condition_path)
    if output.exists():
        raise ValueError("기존 실행 결과를 덮어쓸 수 없습니다")
    output.mkdir(parents=True)
    os.chmod(output, 0o700)
    settings = Settings(
        _env_file=None,
        **(
            settings.model_dump()
            | {"pack_root": condition.overlay.base_root, "storage_dir": output / "storage"}
        ),
    )
    ledger: list[dict[str, Any]] = []
    client = metered_client(
        settings, output, ledger, previous_usd=previous_usd, allocation=allocation
    )
    schema = "evaluation_" + uuid4().hex
    with psycopg.connect(str(settings.app_database_url), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    pool = create_pool(settings, schema=schema)
    apply_schema(pool)
    graph = create_evaluation_graph(settings, create_checkpointer(pool), condition, client=client)
    runner = Runner(pool, graph, settings)
    manifest = {
        **condition.provenance(),
        "schema": schema,
        "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(),
        "settings": {
            name: getattr(settings, name)
            for name in [
                "design_model",
                "review_model",
                "review_mode",
                "design_reasoning_effort",
                "review_reasoning_effort",
                "run_concurrency",
                "llm_concurrency",
                "llm_api_retries",
                "max_tokens_per_run",
                "run_timeout_seconds",
                "llm_timeout_seconds",
                "max_structured_retries",
                "max_output_tokens",
                "enable_erd_pdf",
                "enable_function_spec_pdf",
            ]
        },
        "previous_recorded_usd": previous_usd,
        "allocation_usd": allocation,
        "cost_basis": (
            "Frozen 2026-11-10 OpenAI standard text prices incl cache read/write; "
            "estimates, not invoice; excludes other-session unreported spend"
        ),
        "rates": RATES,
        "started_at": time.time(),
    }
    write(output / "execution-plan.json", manifest)
    write(output / "condition.json", condition.spec.model_dump(mode="json"))
    results: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    runner.start()
    try:
        with TestClient(create_app(settings, pool)) as api:
            for item in condition.spec.inputs:
                condition.assert_current()
                folder = output / item.case_id
                folder.mkdir()
                row: dict[str, Any] = {
                    "case_id": item.case_id,
                    "design_source": condition.spec.mode,
                    "input_sha256": item.sha256,
                    "complete": False,
                }
                path = condition.resolve(item.path)
                mime = {
                    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ".csv": "text/csv",
                    ".hwp": "application/x-hwp",
                    ".hwpx": "application/hwp+zip",
                }.get(path.suffix.lower())
                if mime is None:
                    raise ValueError("평가 입력 형식을 지원하지 않습니다")
                uploaded = api.post(
                    "/runs",
                    files={"file": (path.name, path.read_bytes(), mime)},
                    data={"pack": condition.overlay.spec.pack},
                )
                if uploaded.status_code != 202:
                    raise ValueError(f"업로드 HTTP {uploaded.status_code}")
                row["run_id"] = uploaded.json()["run_id"]
                jobs.append(
                    {
                        "item": item,
                        "folder": folder,
                        "row": row,
                        "seen": set(),
                        "captured": False,
                        "processing_since": None,
                        "submitted": time.monotonic(),
                    }
                )
            write(output / "private-session.json", dict(api.cookies))
            while jobs:
                for job in list(jobs):
                    row = job["row"]
                    run = row["run_id"]
                    folder = job["folder"]
                    item = job["item"]
                    finish = False
                    try:
                        status = api.get(f"/runs/{run}").json()
                        if status["status"] != "queued" and job["processing_since"] is None:
                            job["processing_since"] = time.monotonic()
                        snap = graph.get_state({"configurable": {"thread_id": run}})
                        design = snap.values.get("design")
                        if design is not None and design.requirements and not job["captured"]:
                            write(
                                folder / "analysis-observation.json", design.model_dump(mode="json")
                            )
                            job["captured"] = True
                        finish = status["status"] in ("completed", "failed", "cancelled")
                        asked = status.get("interrupt")
                        if not finish and asked and asked["interrupt_id"] not in job["seen"]:
                            job["seen"].add(asked["interrupt_id"])
                            kind = asked["kind"]
                            response: dict[str, Any]
                            if kind == "review":
                                write(
                                    folder / f"review-r{status['revision']}.json",
                                    {
                                        "status": status,
                                        "design": design.model_dump(mode="json")
                                        if design
                                        else None,
                                        "failed_branches": snap.values.get("failed_branches", ()),
                                    },
                                )
                                if (
                                    design is None
                                    or snap.values.get("failed_branches")
                                    or any(f.severity.value == "critical" for f in design.findings)
                                ):
                                    row["incomplete_reason"] = (
                                        "blocking_findings_or_incomplete_review"
                                    )
                                    finish = True
                                condition.assert_current()
                                response = {"kind": "review", "decision": "approve", "feedback": ""}
                            elif kind == "extraction":
                                response = {
                                    "kind": "extraction",
                                    "confirmed": True,
                                    "excluded_blocks": [],
                                }
                            else:
                                response = {"kind": "requirements", "answers": []}
                            if not finish:
                                reply = api.post(
                                    f"/runs/{run}/resume",
                                    json={
                                        "interrupt_id": asked["interrupt_id"],
                                        "expected_revision": status["revision"],
                                        "response": response,
                                    },
                                )
                                if reply.status_code != 202:
                                    raise ValueError(f"재개 HTTP {reply.status_code}")
                        if (
                            job["processing_since"] is not None
                            and time.monotonic() - job["processing_since"]
                            > settings.run_timeout_seconds + 30
                        ):
                            row["incomplete_reason"] = "execution_deadline"
                            finish = True
                        if not finish:
                            continue
                        status = api.get(f"/runs/{run}").json()
                        row["status"] = status["status"]
                        snap = graph.get_state({"configurable": {"thread_id": run}})
                        design = snap.values.get("design")
                        write(
                            folder / "final.json",
                            {
                                "status": status,
                                "design": design.model_dump(mode="json") if design else None,
                            },
                        )
                        if status["status"] == "completed":
                            view = api.get(
                                f"/runs/{run}/view",
                                params={"section": "design", "revision": status["revision"]},
                            ).json()
                            files = []
                            for artifact in view["artifacts"]:
                                kind, fmt = artifact["kind"], artifact["file_format"]
                                got = api.get(
                                    f"/runs/{run}/artifacts/{kind}",
                                    params={"file_format": fmt, "revision": status["revision"]},
                                )
                                if (
                                    got.status_code != 200
                                    or hashlib.sha256(got.content).hexdigest() != artifact["hash"]
                                ):
                                    raise ValueError("산출물 다운로드·해시 검증 실패")
                                (folder / f"{kind}.{fmt}").write_bytes(got.content)
                                files.append(artifact)
                            manifest_doc = json.loads((folder / "manifest.json").read_text())
                            if (
                                manifest_doc["run_id"] != run
                                or str(manifest_doc["revision"]) != str(status["revision"])
                                or manifest_doc["source_hash"] != item.sha256
                            ):
                                raise ValueError("manifest 실행·원문·revision 불일치")
                            listed = {
                                (a["kind"], a["file_format"]): a["hash"]
                                for a in manifest_doc["files"]
                            }
                            if any(
                                listed.get((a["kind"], a["file_format"])) != a["hash"]
                                for a in files
                                if a["kind"] != "manifest"
                            ):
                                raise ValueError("manifest 파일 해시 불일치")
                            if design is None or manifest_doc["model_hash"] != model_hash(design):
                                raise ValueError("manifest 모델 해시 불일치")
                            if settings.enable_erd_pdf and settings.enable_function_spec_pdf:
                                expected = {
                                    ("functions", "md"),
                                    ("functions", "pdf"),
                                    ("erd", "mmd"),
                                    ("erd", "pdf"),
                                    ("ddl", "sql"),
                                    ("rtm", "xlsx"),
                                    ("rtm", "csv"),
                                    ("manifest", "json"),
                                }
                                if {(a["kind"], a["file_format"]) for a in files} != expected:
                                    raise ValueError("두 PDF·8종 산출물이 완전하지 않습니다")
                            write(folder / "artifacts.json", files)
                            row.update(
                                complete=True,
                                artifact_count=len(files),
                                revision=status["revision"],
                            )
                        if status["status"] in ("completed", "failed", "cancelled"):
                            stream = api.get(f"/runs/{run}/events")
                            (folder / "events.sse").write_text(stream.text)
                    except Exception as exc:
                        row.update(
                            complete=False, error_type=type(exc).__name__, error_message=str(exc)
                        )
                        finish = True
                    if finish:
                        calls = [r for r in ledger if r.get("run_id") == run]
                        row.update(
                            duration_ms=round((time.monotonic() - job["submitted"]) * 1000),
                            call_count=len(calls),
                            estimated_usd=sum(r.get("estimated_usd") or 0 for r in calls),
                        )
                        results.append(row)
                        jobs.remove(job)
                        write(output / "progress.json", {"results": results, "pending": len(jobs)})
                if jobs:
                    time.sleep(0.15)
    finally:
        runner.stop()
        pool.close()
    report = {
        **manifest,
        "finished_at": time.time(),
        "results": results,
        "completed": sum(r["complete"] for r in results),
        "total": len(results),
        "calls": len(ledger),
        "unestimated_calls": sum(r.get("estimated_usd") is None for r in ledger),
        "estimated_usd": sum(r.get("estimated_usd") or 0 for r in ledger),
        "fresh_generation": condition.spec.mode == "fresh_generation",
        "blind_evaluation": False,
        "semantic_scores": None,
    }
    write(output / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="승인된 탐색 조건으로 실제 API 전체 파이프라인 실행"
    )
    parser.add_argument("condition", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--pdf", action="store_true")
    parser.add_argument("--previous-recorded-usd", type=float, default=0)
    parser.add_argument("--allocation-usd", type=float, default=100)
    args = parser.parse_args()
    settings = Settings(
        _env_file=args.env_file if args.env_file else None,
        enable_erd_pdf=args.pdf,
        enable_function_spec_pdf=args.pdf,
    )
    report = execute(
        args.condition,
        settings,
        args.out,
        previous_usd=args.previous_recorded_usd,
        allocation=args.allocation_usd,
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("completed", "total", "calls", "estimated_usd", "design_source")
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["completed"] == report["total"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
