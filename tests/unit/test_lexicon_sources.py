"""출처·정의 대응이 끊긴 운영 어휘는 빌드와 실제 로딩 양쪽에서 거절한다."""

import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from specton.codegen.naming import load_pack_lexicon, physical_name
from specton.packs.build import DEFAULT_ROOT, BuildError, build, read_yaml
from specton.packs.lexicon_sources import LexiconSourceError, validate_lexicon_sources
from specton.packs.loader import PackError, load_pack
from specton.packs.provenance import policy_digest


@pytest.fixture
def root(tmp_path: Path) -> Path:
    target = tmp_path / "packs"
    shutil.copytree(DEFAULT_ROOT, target)
    return target


def edit(root: Path, relative: str, change: Callable[[dict[str, Any]], None]) -> None:
    path = root / "inventory" / relative
    data = read_yaml(path)
    change(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def test_registered_source_rows_match_the_actual_dictionary() -> None:
    assert len(validate_lexicon_sources(DEFAULT_ROOT / "inventory")) == 3
    assert load_pack("inventory").manifest.version == "0.1.23"
    lexicon = load_pack_lexicon("inventory")
    assert physical_name("금형번호", lexicon) == "mld_no"
    assert physical_name("출처없는새낱말번호", lexicon) is None


@pytest.mark.parametrize(
    "entrypoint",
    [
        build,
        lambda root: load_pack("inventory", root=root),
        lambda root: load_pack_lexicon("inventory", root),
    ],
)
@pytest.mark.parametrize(
    "damage",
    [
        "source_hash",
        "missing_source",
        "missing_catalog",
        "missing_candidate",
        "wrong_row",
        "forged_abbreviation",
        "unlisted_word",
        "excluded_word",
        "free_alias",
        "empty_reason",
        "classifier",
        "wrong_excluded_reference",
        "missing_declaration",
        "baseline_hash",
    ],
)
def test_broken_evidence_cannot_enter_the_operational_dictionary(
    root: Path,
    entrypoint: Callable[[Path], object],
    damage: str,
) -> None:
    folder = root / "inventory"
    if damage == "source_hash":
        with (folder / "sources/knps_20240911.csv").open("ab") as file:
            file.write(b"changed")
    elif damage == "missing_source":
        (folder / "sources/knps_20240911.csv").unlink()
    elif damage == "missing_catalog":
        (folder / "lexicon_sources.yaml").unlink()
    elif damage == "missing_candidate":
        edit(root, "lexicon_sources.yaml", lambda d: d["candidates"].pop(0))
    elif damage == "wrong_row":
        edit(root, "lexicon_sources.yaml", lambda d: d["candidates"][0].update(row=2))
    elif damage == "forged_abbreviation":
        edit(root, "words.yaml", lambda d: d["words"][-4].update(abbreviation="FAKE"))
    elif damage == "unlisted_word":
        edit(
            root,
            "words.yaml",
            lambda d: d["words"].append(dict(d["words"][-1], word="출처없는새낱말")),
        )
    elif damage == "excluded_word":
        edit(root, "words.yaml", lambda d: d["words"].append(dict(d["words"][-1], word="양품")))
    elif damage == "free_alias":
        edit(root, "words.yaml", lambda d: d["words"][-1].update(synonyms=["새별칭"]))
    elif damage == "classifier":
        edit(root, "words.yaml", lambda d: d["words"][-1].update(is_classifier=True))
    elif damage == "wrong_excluded_reference":
        edit(
            root,
            "lexicon_sources.yaml",
            lambda d: d["candidates"][-1].update(source="missing", row=2),
        )
    elif damage == "missing_declaration":
        edit(root, "manifest.yaml", lambda d: d.pop("lexicon_sources"))
    elif damage == "baseline_hash":
        with (folder / "sources/words_0.1.21.yaml").open("ab") as file:
            file.write(b"changed")
    else:
        edit(root, "lexicon_sources.yaml", lambda d: d["candidates"][0].update(reason=" "))
    with pytest.raises((BuildError, PackError)):
        entrypoint(root)


@pytest.mark.parametrize("escape", ["../outside.csv", "/tmp/outside.csv", "sources/escape.csv"])
def test_source_paths_cannot_escape_the_pack(root: Path, escape: str) -> None:
    if escape == "sources/escape.csv":
        (root / "inventory" / escape).symlink_to(
            root / "sources/common_standard_words_20251101.csv"
        )
    edit(root, "lexicon_sources.yaml", lambda d: d["sources"]["knps"].update(path=escape))
    with pytest.raises(LexiconSourceError, match="경로"):
        validate_lexicon_sources(root / "inventory")


def test_nfc_duplicate_candidates_are_rejected(root: Path) -> None:
    import unicodedata

    def duplicate(data: dict[str, Any]) -> None:
        entry = dict(data["candidates"][0])
        entry["word"] = unicodedata.normalize("NFD", entry["word"])
        data["candidates"].append(entry)

    edit(root, "lexicon_sources.yaml", duplicate)
    with pytest.raises(LexiconSourceError, match="NFC"):
        validate_lexicon_sources(root / "inventory")


def test_provenance_metadata_is_hashed_and_source_tampering_is_rejected(root: Path) -> None:
    before = policy_digest(root, "inventory")
    edit(root, "lexicon_sources.yaml", lambda d: d["selection"].update(policy_version="v2"))
    assert policy_digest(root, "inventory") != before
    source = root / "inventory/sources/hf_20260727.csv"
    source.write_bytes(source.read_bytes() + b"\r\n")
    with pytest.raises(LexiconSourceError, match="sha256"):
        policy_digest(root, "inventory")


def test_source_snapshot_hash_mode_is_raw_bytes(root: Path) -> None:
    source = root / "inventory/sources/hf_20260727.csv"
    source.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
    with pytest.raises(LexiconSourceError, match="sha256"):
        validate_lexicon_sources(root / "inventory")
    edit(
        root,
        "lexicon_sources.yaml",
        lambda d: d["sources"]["hf"].update(sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
    )
    assert len(validate_lexicon_sources(root / "inventory")) == 3


def test_legacy_pack_without_source_declaration_keeps_previous_policy_hash(root: Path) -> None:
    import hashlib

    from specton.packs.build import pack_content_hash

    folder = root / "inventory"
    edit(root, "manifest.yaml", lambda d: d.pop("lexicon_sources"))
    (folder / "lexicon_sources.yaml").unlink()
    assert validate_lexicon_sources(folder) == ()
    digest = hashlib.sha256()
    for name in ("common", "inventory"):
        digest.update(f"{name}:{pack_content_hash(root / name)}\n".encode())
    sources = root / "sources/sources.yaml"
    digest.update(sources.read_bytes().replace(b"\r\n", b"\n"))
    for key, spec in sorted(read_yaml(sources)["files"].items()):
        digest.update(key.encode() + b"\0")
        digest.update((sources.parent / spec["path"]).read_bytes().replace(b"\r\n", b"\n"))
    assert policy_digest(root, "inventory") == digest.hexdigest()
