"""내부 ID 계산 (`specton/ids.py`, ADR-0016)."""

import unicodedata

from specton.codegen import normalize
from specton.ids import ID_HEX_LENGTH, stable_id
from specton.nodes import a03_entities


def test_a03_and_normalization_use_the_same_id_function() -> None:
    """A03 엔티티·속성 ID와 정리 결과 ID가 한 계산을 쓴다 (한쪽만 바뀌지 않게, #129 리뷰)."""
    assert a03_entities.stable_id is stable_id
    assert normalize.stable_id is stable_id


def test_same_parts_give_the_same_id_and_hangul_forms_are_matched() -> None:
    nfc = stable_id("ATTR", "inventory", "창고", "창고코드")
    nfd = stable_id(
        "ATTR",
        "inventory",
        unicodedata.normalize("NFD", "창고"),
        unicodedata.normalize("NFD", "창고코드"),
    )
    assert nfc == nfd == stable_id("ATTR", "inventory", "창고", "창고코드")
    prefix, digest = nfc.split("-")
    assert prefix == "ATTR"
    assert len(digest) == ID_HEX_LENGTH


def test_piece_boundaries_and_prefix_change_the_id() -> None:
    assert stable_id("ENT", "ab", "c") != stable_id("ENT", "a", "bc")
    assert stable_id("ENT", "inventory", "창고") != stable_id("TBL", "inventory", "창고")
