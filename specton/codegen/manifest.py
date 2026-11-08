"""출력 manifest: 한 revision의 산출물이 어느 실행·모델·버전에서 나왔는지 (#14, docs/10).

`run_id`·`revision`·`model_hash`·원문 해시·팩·프롬프트·생성기 버전·파일별 해시를 담는다.
초안과 승인본을 섞지 않는다: 한 manifest에는 같은 revision·같은 승인 상태의 파일만 넣는다.
파일 묶음 내려받기·승인본 게시가 이 값을 함께 내보낸다 (연결은 #17·#13).
이 모듈은 LLM client를 import하지 않는다 (CLAUDE.md, `codegen/` 규칙).
"""

import json
from collections.abc import Iterable
from typing import Any

from specton.artifacts import GeneratedArtifact
from specton.codegen.function_spec import document_info
from specton.contracts import DesignState
from specton.model_hash import model_hash


def build_manifest(design: DesignState, generated: Iterable[GeneratedArtifact]) -> dict[str, Any]:
    """현재 revision 산출물의 manifest. 다른 revision·모델·승인 상태가 섞이면 ValueError."""
    digest = model_hash(design)
    files = sorted(generated, key=lambda g: (g["ref"].kind, g["ref"].file_format))
    if not files:
        raise ValueError("manifest: 산출물이 없습니다")
    for item in files:
        ref = item["ref"]
        if ref.revision != design.revision or item["model_hash"] != digest:
            raise ValueError(
                f"manifest: {ref.kind}.{ref.file_format}이 현재 모델에서 나오지 않았습니다"
            )
    approved = {g["ref"].approved for g in files}
    if len(approved) != 1:
        raise ValueError("manifest: 초안과 승인본을 한 manifest에 섞을 수 없습니다")
    normalized = design.normalized
    return {
        **document_info(design),
        "source_hash": design.versions.document_hash,
        "approved": approved.pop(),
        "prompt_versions": dict(sorted(design.versions.prompt_versions.items())),
        "model_names": dict(sorted(design.versions.model_names.items())),
        "generator_versions": {
            "normalize_rules": None if normalized is None else normalized.rules_version,
            "lexicon_digest": None if normalized is None else normalized.lexicon_digest,
        },
        "files": [
            {"kind": g["ref"].kind, "file_format": g["ref"].file_format, "hash": g["ref"].hash}
            for g in files
        ],
    }


def render_manifest(manifest: dict[str, Any]) -> bytes:
    """사람과 도구가 읽는 JSON. 키 순서를 고정해 같은 내용이면 같은 바이트다."""
    return (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
