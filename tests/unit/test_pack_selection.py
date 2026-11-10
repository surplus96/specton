"""선별 적용 기록은 형식만 아닌 실제 공식 이음동의어·금칙어 관계와 대조한다."""

import shutil
import subprocess
import sys
from pathlib import Path
from unicodedata import normalize

import pytest
import yaml

from specton.packs.build import DEFAULT_ROOT, BuildError, build, read_yaml
from specton.packs.loader import PackError, load_pack
from specton.packs.selection import validate_selection

OFFICIAL = [dict(word="대장", synonyms=["장부"], forbidden_synonyms=["장부금칙"])]


def write(folder: Path, *, words=("장부",), entries=None):
    folder.mkdir(exist_ok=True)
    (folder / "words.yaml").write_text(
        yaml.safe_dump({"words": [{"word": w} for w in words]}, allow_unicode=True)
    )
    if entries is not None:
        (folder / "standard_selection.yaml").write_text(
            yaml.safe_dump({"exceptions": entries}, allow_unicode=True)
        )


@pytest.mark.parametrize("word", ["장부", "장부금칙", " 장부 ", normalize("NFD", "장부")])
def test_unlisted_official_alias_or_forbidden_word_is_rejected(tmp_path, word):
    write(tmp_path, words=(word,))
    with pytest.raises(BuildError, match="선별 적용 목록"):
        validate_selection(tmp_path, OFFICIAL)


@pytest.mark.parametrize("target,reason", [("다른표준어", "선택 이유"), ("대장", "  ")])
def test_wrong_standard_word_and_blank_reason_are_rejected(tmp_path, target, reason):
    write(tmp_path, entries=[dict(word="장부", standard_word=target, reason=reason)])
    with pytest.raises(BuildError):
        validate_selection(tmp_path, OFFICIAL)


def test_valid_selection_is_accepted_and_stale_selection_is_rejected(tmp_path):
    entries = [dict(word="장부", standard_word="대장", reason="기존 개발 용어 유지")]
    write(tmp_path, entries=entries)
    validate_selection(tmp_path, OFFICIAL)
    write(tmp_path, words=())
    with pytest.raises(BuildError, match="불필요"):
        validate_selection(tmp_path, OFFICIAL)


def test_real_loader_and_builder_both_reject_unlisted_alias(tmp_path):
    root = tmp_path / "packs"
    shutil.copytree(DEFAULT_ROOT, root)
    path = root / "inventory/standard_selection.yaml"
    path.unlink()
    with pytest.raises(PackError, match="장부"):
        load_pack("inventory", root=root)
    with pytest.raises(BuildError, match="장부"):
        build(root)
    result = subprocess.run(
        [sys.executable, "-m", "specton.packs.build", "--root", str(root), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and "장부" in result.stderr
    assert "Traceback" not in result.stderr


def test_real_inventory_selection_and_versions_are_frozen():
    loaded = load_pack("inventory")
    assert loaded.manifest.status == loaded.common.manifest.status == "approved"
    assert loaded.common.manifest.version == "0.1.4"
    assert loaded.manifest.version == "0.1.21"
    assert (
        read_yaml(DEFAULT_ROOT / "inventory/standard_selection.yaml")["exceptions"][0][
            "standard_word"
        ]
        == "대장"
    )


@pytest.mark.parametrize(
    "data", [{"exceptions": None}, {"exceptions": {}}, {"exceptions": ["장부"]}]
)
def test_malformed_selection_is_a_build_error(tmp_path, data):
    write(tmp_path)
    (tmp_path / "standard_selection.yaml").write_text(yaml.safe_dump(data, allow_unicode=True))
    with pytest.raises(BuildError):
        validate_selection(tmp_path, OFFICIAL)
