"""큰 공식 사전의 빠른 파서와 대체 파서 모두 안전 생성자만 사용한다."""

from pathlib import Path

import pytest
import yaml

from specton.packs.build import read_yaml
from specton.packs.loader import PackError, _read_data


@pytest.mark.parametrize("without_c_loader", [False, True])
def test_pack_parsers_reject_python_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, without_c_loader: bool
) -> None:
    if without_c_loader:
        monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    path = tmp_path / "pack.yaml"
    path.write_text("!!python/object/apply:builtins.dict []\n")
    with pytest.raises(yaml.YAMLError):
        read_yaml(path)
    with pytest.raises(PackError, match="형식"):
        _read_data(path)
    path.write_text("words:\n- word: code\n  abbreviation: CD\n")
    assert (
        read_yaml(path) == _read_data(path) == {"words": [{"word": "code", "abbreviation": "CD"}]}
    )
