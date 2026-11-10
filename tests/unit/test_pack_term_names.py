"""팩 용어 이름 NFC·공백 충돌 검사 (#264)."""

from unicodedata import normalize

from specton.packs.term_names import term_name_conflicts

NFD_WAREHOUSE = normalize("NFD", "창고")
COMPOSITION = "한글 조합 방식(NFC·NFD)만 다른"
SPACING = "앞뒤 공백만 다른"


def test_nfd_fixture_really_differs_from_nfc() -> None:
    # 편집기가 NFC로 바꿔 시험이 헛도는 것을 막는다.
    assert NFD_WAREHOUSE != "창고"
    assert normalize("NFC", NFD_WAREHOUSE) == "창고"


def test_distinct_names_pass() -> None:
    assert term_name_conflicts([("창고", ()), ("창고코드", ["보관소코드"]), ("품목명", [])]) == []


def test_exact_same_string_is_reported_without_composition_hint() -> None:
    problems = term_name_conflicts([("창고", ()), ("창고", ())])

    assert len(problems) == 1
    assert "1번째 '창고', 2번째 '창고'" in problems[0]
    assert "완전히 같은 문자열" in problems[0]
    assert COMPOSITION not in problems[0]


def test_nfc_and_nfd_names_are_reported_with_composition_hint() -> None:
    problems = term_name_conflicts([("창고", ()), (NFD_WAREHOUSE, ())])

    assert len(problems) == 1
    assert "용어 이름 중복 '창고'" in problems[0]
    assert COMPOSITION in problems[0]


def test_three_names_mixing_same_string_and_nfd_report_both_causes() -> None:
    problems = term_name_conflicts([("창고", ()), ("창고", ()), (NFD_WAREHOUSE, ())])

    assert len(problems) == 1
    assert "3번째" in problems[0]
    assert problems[0].endswith(
        "완전히 같은 문자열 반복과 한글 조합 방식(NFC·NFD) 차이가 함께 있습니다"
    )


def test_three_names_mixing_same_string_and_space_report_both_causes() -> None:
    problems = term_name_conflicts([("창고", ()), ("창고", ()), (" 창고", ())])

    assert problems[0].endswith("완전히 같은 문자열 반복과 앞뒤 공백 차이가 함께 있습니다")


def test_repeat_with_space_and_nfd_reports_all_three_causes() -> None:
    problems = term_name_conflicts([("창고", ()), ("창고", ()), (" " + NFD_WAREHOUSE, ())])

    assert problems[0].endswith(
        "완전히 같은 문자열 반복과 앞뒤 공백·한글 조합 방식(NFC·NFD) 차이가 함께 있습니다"
    )


def test_three_identical_names_are_only_an_exact_repeat() -> None:
    problems = term_name_conflicts([("창고", ()), ("창고", ()), ("창고", ())])

    assert problems[0].endswith(": 완전히 같은 문자열이 반복됩니다")


def test_leading_or_trailing_space_is_the_same_name() -> None:
    problems = term_name_conflicts([("창고", ()), (" 창고", ())])

    assert len(problems) == 1
    assert "' 창고'" in problems[0]
    assert SPACING in problems[0]


def test_space_and_nfd_together_mention_both_causes() -> None:
    problems = term_name_conflicts([("창고", ()), (" " + NFD_WAREHOUSE, ())])

    assert len(problems) == 1
    assert "앞뒤 공백과 한글 조합 방식(NFC·NFD)이 다른" in problems[0]


def test_same_spacing_but_different_composition_is_only_composition() -> None:
    problems = term_name_conflicts([(" 창고", ()), (" " + NFD_WAREHOUSE, ())])

    assert len(problems) == 1
    assert COMPOSITION in problems[0]


def test_synonym_equal_to_another_official_term_is_rejected() -> None:
    problems = term_name_conflicts([("창고", ()), ("보관소", ["창고"])])

    assert problems == [
        "2번째 용어 '보관소'의 동의어 '창고'가 다른 정식 용어 '창고'(1번째)와 같습니다"
    ]


def test_synonym_equal_after_nfc_or_strip_is_rejected_with_cause() -> None:
    problems = term_name_conflicts([("창고", ()), ("보관소", [NFD_WAREHOUSE, " 창고 "])])

    assert len(problems) == 2
    assert COMPOSITION in problems[0]
    assert SPACING in problems[1]


def test_synonym_equal_to_own_name_is_allowed() -> None:
    assert term_name_conflicts([("창고", ["창고", NFD_WAREHOUSE, " 창고"])]) == []


def test_terms_sharing_a_synonym_are_not_checked_here() -> None:
    assert term_name_conflicts([("창고", ["보관소"]), ("창고코드", ["보관소"])]) == []


def test_blank_synonym_is_ignored() -> None:
    assert term_name_conflicts([("창고", ["  "])]) == []


def test_all_problems_are_collected_in_input_order() -> None:
    terms = [
        ("품목", ["창고"]),
        ("창고", ()),
        ("품목", ()),
        (NFD_WAREHOUSE, ()),
    ]

    problems = term_name_conflicts(terms)

    assert len(problems) == 3
    assert problems[0].startswith("용어 이름 중복 '품목'")  # 1번째에서 처음 나온 이름이 먼저
    assert problems[1].startswith("용어 이름 중복 '창고'")
    assert problems[2].startswith("1번째 용어 '품목'의 동의어 '창고'")
    assert term_name_conflicts(terms) == problems  # 같은 입력이면 순서까지 같다
