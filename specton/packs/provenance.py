"""팩 고정 근거. 경로·줄바꿈에 독립적인 내용 해시를 정리 결과에 보존한다."""

import hashlib
from pathlib import Path

from specton.packs.build import pack_content_hash, read_yaml
from specton.packs.lexicon_sources import source_fingerprint


def policy_digest(root: Path, pack: str) -> str:
    digest = hashlib.sha256()
    for name in ("common", pack):
        digest.update(f"{name}:{pack_content_hash(root / name)}\n".encode())
    if evidence := source_fingerprint(root / pack):
        digest.update(f"lexicon_sources:{evidence}\n".encode())
    sources = root / "sources/sources.yaml"
    if sources.is_file():
        digest.update(sources.read_bytes().replace(b"\r\n", b"\n"))
        for key, spec in sorted(read_yaml(sources)["files"].items()):
            digest.update(key.encode() + b"\0")
            digest.update((sources.parent / spec["path"]).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


class ExecutionPolicyError(ValueError):
    """사용자에게 전달할 안전한 정책 변경 안내. 파일 경로·내부 예외는 포함하지 않는다."""


def capture_policy(root: Path, pack: str) -> dict[str, str]:
    return {
        "common_version": str(read_yaml(root / "common/manifest.yaml")["version"]),
        "policy_digest": policy_digest(root, pack),
    }


def verify_policy(root: Path, pack: str, common_version: str | None, digest: str | None) -> None:
    if common_version is None and digest is None:
        return  # 저수준 직접 호출 호환. API 실행은 등록 시 두 값을 항상 고정한다.
    if not common_version or not digest:
        raise ExecutionPolicyError("실행 정책 기록이 불완전합니다. 새 실행이 필요합니다.")
    current = capture_policy(root, pack)
    if current != {"common_version": common_version, "policy_digest": digest}:
        raise ExecutionPolicyError("팩·검사 정책이 변경되었습니다. 새 실행이 필요합니다.")
