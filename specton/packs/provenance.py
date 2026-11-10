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
