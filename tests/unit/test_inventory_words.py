"""재고 팩 단어: A03이 실제 실행(2026-11-06)에서 만든 이름이 사전으로 물리명이 되는지 본다.

그 실행에서 저장된 모델을 정리 코드(`normalize_design`)에 직접 넣으면, 아래 이름을 사전으로
풀지 못해 `UNRESOLVED_NAME` 11건이 났다. 이 시험은 그 이름 11개가 재고 팩 사전
(`inventory/words.yaml`·공통 단어)만으로 물리명이 되는지 확인한다. 기대값은 팩 파일의 단어 약어를
이어 붙인 값이다. 엔티티 이름 5개는 그날 실행의 예이고, A03은 실행마다 다른 이름을 지을 수 있다.
장부(`BK`)는 공통표준 단어가 아니어서 팩에서 정한 약어다
(공통표준은 장부를 대장 LDGR의 이음동의어로 둠).
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
    # 개발용 합성 세트 실제 실행(2026-11-10, #291)에서 풀리지 않던 낱말. 약어는 공개 표준사전 값이다
    "간선권역명": "mnn_sarea_nm",
    "거점명": "fthl_nm",
    "금형번호": "mld_no",
    "연차": "cnyr",
}


@pytest.mark.parametrize(("logical", "physical"), EXPECTED.items())
def test_names_from_the_real_inventory_run_resolve(logical: str, physical: str) -> None:
    lexicon = load_pack_lexicon("inventory", DEFAULT_PACK_ROOT)

    assert physical_name(logical, lexicon) == physical
