"""재고 팩 단어: A03·A04가 실제 실행(2026-11-06)에서 만든 이름이 사전으로 물리명이 되는지 본다.

실제 실행에서 정리(`normalize`)는 아래 이름을 사전으로 풀지 못해 `UNRESOLVED_NAME` 11건으로 멈췄다.
이 시험은 그 이름 11개가 재고 팩 사전(`inventory/words.yaml`·공통 단어)만으로 물리명이 되는지
확인한다. 기대값은 팩 파일의 단어 약어를 이어 붙인 값이다. 장부(`BK`)만 공통표준에 없어
팩에서 새로 정한 약어다(공통표준 장부가액 BKVL의 앞부분).
"""

import pytest

from specton.codegen.naming import DEFAULT_PACK_ROOT, load_pack_lexicon, physical_name

EXPECTED = {
    "로트번호": "lt_no",
    "입고일": "wrhs_day",
    "장부재고수량": "bk_invt_qty",
    "보관위치": "kpng_pstn",
    "실사수량": "acinsp_qty",
    "안전재고수량": "sfty_invt_qty",
    "재고변경기록": "invt_chg_rcd",
    "자재거래이력": "mtrl_dlng_hstry",
    "로트재고": "lt_invt",
    "재고실사결과": "invt_acinsp_rslt",
    "자재": "mtrl",
}


@pytest.mark.parametrize(("logical", "physical"), EXPECTED.items())
def test_names_from_the_real_inventory_run_resolve(logical: str, physical: str) -> None:
    lexicon = load_pack_lexicon("inventory", DEFAULT_PACK_ROOT)

    assert physical_name(logical, lexicon) == physical
