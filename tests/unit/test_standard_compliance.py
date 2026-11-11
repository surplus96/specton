"""표준 준수 검사 SC-01~06 (#15, TC-F13). 공통표준 원본과 팩 낱말로 정리된 속성 칸을 본다."""

import csv
import shutil
from pathlib import Path
from typing import Any

import pytest

from specton.codegen.naming import DEFAULT_PACK_ROOT
from specton.codegen.normalize_step import normalize_design
from specton.contracts import DesignState, Function, Requirement
from specton.contracts.base import SqlType, TargetStage
from specton.contracts.findings import Severity
from specton.contracts.normalized import Column, Normalized, NormalizedModel, Table
from specton.contracts.state import VersionInfo
from specton.nodes.a03_entities import A03Output, _with_ids
from specton.packs.build import RETIRED, RETIRED_COLUMN, read_yaml
from specton.packs.examples import load_examples
from specton.packs.loader import Word
from specton.review.standard_compliance import (
    CODES,
    DomainSpec,
    OfficialStandard,
    OfficialTerm,
    OfficialWord,
    Profile,
    StandardComplianceReview,
    check_standard_compliance,
    compliance_severities,
    load_official_standard,
    pack_words,
    split_by_abbreviation,
    split_from_end,
)

SOURCES = DEFAULT_PACK_ROOT / "sources"
SEVERITIES = {
    "SC-01": Severity.MINOR,
    "SC-02": Severity.MINOR,
    "SC-03": Severity.MAJOR,
    "SC-04": Severity.MAJOR,
    "SC-05": Severity.MAJOR,
    "SC-06": Severity.MAJOR,
}


# ── 고정 데이터 ───────────────────────────────────────────────────────


def _word(
    word: str, abbreviation: str, *, classifier: bool = False, group: str | None = None
) -> Word:
    return Word(
        word=word,
        abbreviation=abbreviation,
        english=abbreviation,
        definition=word,
        is_classifier=classifier,
        domain_group=group,
    )


# 팩에 등록한 낱말 (공통 팩·도메인 팩 words.yaml 역할)
WORDS = (
    _word("배정", "ALTMNT"),
    _word("구분", "SE"),
    _word("일자", "YMD", classifier=True, group="연월일"),
    _word("코드", "CD", classifier=True, group="코드"),
    _word("장부", "BK"),  # 공식 금칙어지만 팩에 일부러 등록한 낱말 (재고 팩 「장부」와 같은 경우)
)


def _official() -> OfficialStandard:
    """작은 공통표준. 연월일C8은 strict에서 char(8), pg_native에서 date다(실제 팩과 같은 변환)."""
    date = {
        "strict": DomainSpec("연월일", SqlType.CHAR, 8, None),
        "pg_native": DomainSpec("연월일", SqlType.DATE, None, None),
    }
    code = {
        "strict": DomainSpec("코드", SqlType.VARCHAR, 10, None),
        "pg_native": DomainSpec("코드", SqlType.VARCHAR, 10, None),
    }
    return OfficialStandard(
        edition="공통표준 시험판",
        sha256={"words": "w", "terms": "t", "domains": "d"},
        words={
            "배정": OfficialWord("ALTMNT", False, None, ()),
            "일자": OfficialWord("YMD", True, "연월일", ()),
            "코드": OfficialWord("CD", True, "코드", ()),
            "경로": OfficialWord("PATH", False, None, ("패스",), ("루트",)),
            "대장": OfficialWord("LDGR", False, None, ("장부",)),
        },
        terms={
            "배정일자": OfficialTerm("ALTMNT_YMD", "연월일C8"),
            "경로코드": OfficialTerm("PATH_CD", "코드C10"),
        },
        domains={"연월일C8": date, "코드C10": code},
        class_types={
            "연월일": {"strict": frozenset({SqlType.CHAR}), "pg_native": frozenset({SqlType.DATE})},
            "코드": {
                "strict": frozenset({SqlType.VARCHAR}),
                "pg_native": frozenset({SqlType.VARCHAR}),
            },
        },
    )


def _col(
    col_id: str,
    name: str,
    physical: str,
    data_type: SqlType,
    length: int | None = None,
    **kw: Any,
) -> Column:
    base: dict[str, Any] = {
        "id": col_id,
        "name": name,
        "physical_name": physical,
        "data_type": data_type,
        "length": length,
        "precision": None,
        "scale": None,
        "time_precision": None,
        "domain": None,
        "nullable": True,
        "req_ids": ("REQ-01",),
        "attribute_id": f"ATTR-{col_id}",
    }
    return Column.model_validate({**base, **kw})


def _design(*columns: Column, iteration: int = 0) -> DesignState:
    key = _col("K", "배정코드", "altmnt_cd", SqlType.VARCHAR, 10, domain="코드C10", nullable=False)
    table = Table(
        id="TBL-1",
        name="배정",
        physical_name="altmnt",
        columns=(key, *columns),
        primary_key=("K",),
        unique_keys=(),
        req_ids=("REQ-01",),
        entity_id="ENT-1",
    )
    model = NormalizedModel(
        pack="inventory",
        pack_version="1",
        rules_version="1",
        lexicon_digest="abc",
        tables=(table,),
        foreign_keys=(),
    )
    return DesignState(run_id="run-1", iteration=iteration, normalized=model)


def _check(
    *columns: Column, profile: Profile = "strict", words: tuple[Word, ...] = WORDS
) -> StandardComplianceReview:
    return check_standard_compliance(
        _design(*columns), official=_official(), words=words, severities=SEVERITIES, profile=profile
    )


def _codes(review: StandardComplianceReview) -> list[str]:
    return [f.rule_code or "" for f in review["findings"]]


def _item(review: StandardComplianceReview, code: str) -> tuple[int, int, int, int]:
    [item] = [i for i in review["items"] if i.code == code]
    return item.total, item.diagnosed, item.undiagnosed, item.compliant


# ── 팩 설정 ───────────────────────────────────────────────────────────


def test_sc_severities_come_from_rules_yaml() -> None:
    # R1 11/9 답: SC는 critical을 쓰지 않는다 (ADR-0010 SC 예외)
    assert compliance_severities() == SEVERITIES


def test_missing_severity_stops_only_when_that_finding_is_needed() -> None:
    column = _col("C1", "배정구분", "altmnt_se", SqlType.VARCHAR, 2)
    without_sc02 = {k: v for k, v in SEVERITIES.items() if k != "SC-02"}
    with pytest.raises(ValueError, match="SC-02의 심각도"):
        check_standard_compliance(
            _design(column), official=_official(), words=WORDS, severities=without_sc02,
            profile="strict",
        )  # fmt: skip
    fine = _col("C1", "배정일자", "altmnt_ymd", SqlType.CHAR, 8)
    review = check_standard_compliance(
        _design(fine), official=_official(), words=WORDS, severities=without_sc02, profile="strict"
    )
    assert review["findings"] == ()


def test_requires_a_successful_normalization() -> None:
    with pytest.raises(ValueError, match="정리 결과"):
        check_standard_compliance(
            DesignState(run_id="run-1"), official=_official(), words=WORDS,
            severities=SEVERITIES, profile="strict",
        )  # fmt: skip


# ── 대상 ──────────────────────────────────────────────────────────────


def test_pack_term_columns_and_fk_columns_are_not_targets() -> None:
    # 팩 용어 칸은 A03 출력 검사·RULE-03이, FK 칸은 부모 칸이 본다. 같은 원인을 다시 내지 않는다.
    term = _col("C1", "배정구분", "altmnt_se", SqlType.VARCHAR, 2, domain="코드C10")
    fk = _col(
        "C2", "배정구분", "altmnt_se_2", SqlType.VARCHAR, 2,
        attribute_id=None, relationship_id="REL-01", references="K",
    )  # fmt: skip
    review = _check(term, fk)
    assert review["findings"] == ()
    assert {i.total for i in review["items"]} == {0}
    assert all(i.rate is None for i in review["items"])


# ── SC별 ──────────────────────────────────────────────────────────────


def test_sc01_name_that_no_dictionary_can_split() -> None:
    review = _check(_col("C1", "배정뭐뭐일자", "x", SqlType.CHAR, 8))
    [finding] = review["findings"]
    assert (finding.rule_code, finding.kind, finding.severity, finding.target_stage) == (
        "SC-01",
        "unregistered_word",
        Severity.MINOR,
        None,
    )
    assert [(t.kind, t.id) for t in finding.targets] == [("attribute", "ATTR-C1")]
    assert not review["requires_manual_review"]
    # 나눌 수 없으면 끝 단어·금칙어는 미진단
    assert _item(review, "SC-01") == (1, 1, 0, 0)
    assert _item(review, "SC-02")[1:3] == (0, 1)
    assert _item(review, "SC-04")[1:3] == (0, 1)


def test_sc02_last_word_is_not_a_classifier() -> None:
    review = _check(_col("C1", "배정구분", "altmnt_se", SqlType.VARCHAR, 2))
    [finding] = review["findings"]
    assert (finding.rule_code, finding.kind, finding.severity) == (
        "SC-02",
        "missing_classifier",
        Severity.MINOR,
    )
    assert "구분" in finding.evidence[0].quote
    assert _item(review, "SC-03")[1] == 0  # 분류어가 아니면 도메인 비교 대상이 아니다


@pytest.mark.parametrize(
    ("profile", "data_type", "length", "expected"),
    [
        (
            "strict",
            SqlType.VARCHAR,
            10,
            ["SC-03"],
        ),  # strict 연월일은 char → 타입 다름, SC-06은 내지 않음
        ("strict", SqlType.CHAR, 8, []),
        ("strict", SqlType.CHAR, 10, ["SC-06"]),  # 타입은 같고 길이만 다름
        ("pg_native", SqlType.DATE, None, []),
        ("pg_native", SqlType.CHAR, 8, ["SC-03"]),  # pg_native 연월일은 date
    ],
)
def test_sc03_and_sc06_follow_the_type_profile_and_never_both(
    profile: Profile, data_type: SqlType, length: int | None, expected: list[str]
) -> None:
    review = _check(_col("C1", "배정일자", "altmnt_ymd", data_type, length), profile=profile)
    assert _codes(review) == expected
    for finding in review["findings"]:
        assert finding.target_stage is TargetStage.DATA_MODEL
        assert finding.severity is Severity.MAJOR
    assert not review["requires_manual_review"]


def test_sc03_message_names_the_classifier_and_allowed_types() -> None:
    [finding] = _check(_col("C1", "배정일자", "altmnt_ymd", SqlType.VARCHAR, 10))["findings"]
    assert finding.evidence[0].quote == (
        "배정.배정일자: 분류어 「일자」의 도메인 분류 연월일은 strict 기준 char인데 "
        "칸 타입은 varchar입니다."
    )


def test_sc04_forbidden_word_needs_a_person_unless_the_pack_registered_it() -> None:
    review = _check(_col("C1", "패스코드", "pass_cd", SqlType.VARCHAR, 10))
    [finding] = review["findings"]
    assert (finding.rule_code, finding.kind, finding.severity, finding.target_stage) == (
        "SC-04",
        "forbidden_word:패스",
        Severity.MAJOR,
        None,
    )
    assert "「경로」" in finding.evidence[0].quote
    assert review["requires_manual_review"]
    # 팩에 등록한 낱말은 의도한 선택이라 지적하지 않는다 (R2 11/9, 재고 팩 「장부」)
    assert _check(_col("C1", "장부코드", "bk_cd", SqlType.VARCHAR, 10))["findings"] == ()
    registered = (*WORDS, _word("패스", "PASS"))
    assert (
        _check(_col("C1", "패스코드", "pass_cd", SqlType.VARCHAR, 10), words=registered)["findings"]
        == ()
    )


def test_sc04_synonym_is_a_minor_note_that_needs_no_person() -> None:
    review = _check(_col("C1", "루트코드", "route_cd", SqlType.VARCHAR, 10))
    [finding] = review["findings"]
    # rules.yaml subtypes.synonym: minor·informational (#260)
    assert (finding.rule_code, finding.kind, finding.severity, finding.target_stage) == (
        "SC-04",
        "synonym:루트",
        Severity.MINOR,
        None,
    )
    assert "「경로」" in finding.evidence[0].quote
    assert not review["requires_manual_review"]
    assert _item(review, "SC-04") == (1, 1, 0, 0)
    # 팩에 등록한 낱말(선별 적용 목록의 「장부」와 같은 경우)은 지적하지 않는다
    registered = (*WORDS, _word("루트", "ROUTE"))
    assert (
        _check(_col("C1", "루트코드", "route_cd", SqlType.VARCHAR, 10), words=registered)[
            "findings"
        ]
        == ()
    )


def test_synonym_index_skips_official_words_and_forbidden_words() -> None:
    words = {
        **_official().words,
        # 「배정」은 그 자체로 공식 단어, 「패스」는 이미 금칙어라 이음동의어로 다시 세지 않는다
        "할당": OfficialWord("ASGN", False, None, (), ("배정", "패스", "할애")),
    }
    official = OfficialStandard(**{**vars(_official()), "words": words})
    assert official.synonym_index() == {"루트": "경로", "할애": "할당"}


def test_sc05_same_name_as_an_official_term_but_different_abbreviation() -> None:
    review = _check(_col("C1", "경로코드", "ruut_cd", SqlType.VARCHAR, 10))
    [finding] = review["findings"]
    assert (finding.rule_code, finding.kind, finding.severity, finding.target_stage) == (
        "SC-05",
        "official_term_conflict",
        Severity.MAJOR,
        None,
    )
    assert "RUUT_CD ≠ 공식 PATH_CD" in finding.evidence[0].quote
    assert review["requires_manual_review"]
    assert _check(_col("C1", "경로코드", "path_cd", SqlType.VARCHAR, 10))["findings"] == ()


def test_columns_without_an_official_term_are_undiagnosed_not_passed() -> None:
    review = _check(_col("C1", "구분코드", "se_cd", SqlType.VARCHAR, 10))
    assert review["findings"] == ()
    assert _item(review, "SC-05") == (1, 0, 1, 0)
    assert _item(review, "SC-06") == (1, 0, 1, 0)
    assert _item(review, "SC-03") == (1, 1, 0, 1)


def test_counts_rate_ids_and_repeatability() -> None:
    columns = (
        _col("C1", "배정구분", "altmnt_se", SqlType.VARCHAR, 2),  # SC-02
        _col("C2", "배정일자", "altmnt_ymd", SqlType.CHAR, 8),  # 적합
        _col("C3", "경로코드", "ruut_cd", SqlType.VARCHAR, 10),  # SC-05
        _col("C4", "구분코드", "se_cd", SqlType.VARCHAR, 10),  # SC-05·06 미진단
    )
    first = check_standard_compliance(
        _design(*columns, iteration=2), official=_official(), words=WORDS,
        severities=SEVERITIES, profile="strict",
    )  # fmt: skip
    again = check_standard_compliance(
        _design(*columns, iteration=2), official=_official(), words=WORDS,
        severities=SEVERITIES, profile="strict",
    )  # fmt: skip
    assert first == again
    assert [f.id for f in first["findings"]] == ["SC-02-2-1", "SC-05-2-1"]
    assert len({f.fingerprint for f in first["findings"]}) == 2
    [sc02] = [i for i in first["items"] if i.code == "SC-02"]
    assert (sc02.total, sc02.diagnosed, sc02.compliant, sc02.rate) == (4, 4, 3, 75.0)
    [sc05] = [i for i in first["items"] if i.code == "SC-05"]
    assert (sc05.total, sc05.diagnosed, sc05.undiagnosed, sc05.compliant) == (4, 2, 2, 1)
    assert [i.code for i in first["items"]] == list(CODES)


# ── 공통표준 원본 ─────────────────────────────────────────────────────


def _raw_names(kind: str, column: str) -> tuple[set[str], set[str]]:
    """원본 CSV의 (폐기되지 않은 이름, 폐기된 이름)."""
    files = read_yaml(SOURCES / "sources.yaml")["files"]
    with (SOURCES / files[kind]["path"]).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    live = {r[column].strip() for r in rows if r.get(RETIRED_COLUMN, "").strip() != RETIRED}
    retired = {r[column].strip() for r in rows if r.get(RETIRED_COLUMN, "").strip() == RETIRED}
    return live, retired


def test_real_sources_are_pinned_and_skip_retired_and_clashing_rows() -> None:
    official = load_official_standard()
    assert "8차" in official.edition and "2025-11" in official.edition
    assert set(official.sha256) == {"words", "terms", "domains"}
    live_words, retired_words = _raw_names("words", "공통표준단어명")
    live_terms, retired_terms = _raw_names("terms", "공통표준용어명")
    assert retired_words and retired_terms
    assert not (retired_words - live_words) & set(official.words)
    assert not (retired_terms - live_terms) & set(official.terms)
    # 폐기를 빼도 같은 이름에 내용이 다른 줄이 있으면 어느 줄인지 추측하지 않는다
    assert {"보훈", "중권역"} <= official.ambiguous_words
    assert {"납세자명", "사업자명"} <= official.ambiguous_terms
    assert {"번호C9", "번호C13", "번호C24"} <= official.ambiguous_domains
    assert not official.ambiguous_terms & set(official.terms)
    # 번호C9처럼 이름이 겹치는 도메인도 분류어 타입 비교에는 두 타입을 모두 넣는다
    assert {SqlType.CHAR, SqlType.VARCHAR} <= official.class_types["번호"]["strict"]
    # 「장부」는 공식 단어 「대장」의 이음동의어다(재고 팩 선별 적용 목록과 같은 관계)
    assert "장부" in official.words["대장"].synonyms
    assert official.synonym_index()["장부"] == "대장"


def _copy_sources(tmp_path: Path) -> Path:
    shutil.copytree(SOURCES, tmp_path / "sources")
    return tmp_path


def test_changed_source_file_stops_instead_of_checking_silently(tmp_path: Path) -> None:
    root = _copy_sources(tmp_path)
    words = root / "sources" / read_yaml(SOURCES / "sources.yaml")["files"]["words"]["path"]
    words.write_bytes(words.read_bytes() + b"\n")
    with pytest.raises(ValueError, match=r"sha256이 sources.yaml과 다릅니다"):
        load_official_standard(root=root)


def test_missing_sha256_stops(tmp_path: Path) -> None:
    root = _copy_sources(tmp_path)
    path = root / "sources" / "sources.yaml"
    text = path.read_text(encoding="utf-8")
    start = text.index(", sha256: ")
    path.write_text(text[:start] + text[text.index(" }", start) :], encoding="utf-8")
    with pytest.raises(ValueError, match="sha256이 없습니다"):
        load_official_standard(root=root)


def test_line_endings_of_the_checkout_do_not_change_the_hash(tmp_path: Path) -> None:
    root = _copy_sources(tmp_path)
    for csv_file in (root / "sources").glob("*.csv"):
        csv_file.write_bytes(csv_file.read_bytes().replace(b"\r\n", b"\n"))
    assert load_official_standard(root=root).sha256 == load_official_standard().sha256


def test_real_official_term_with_a_different_abbreviation_needs_a_person() -> None:
    # 「수작업여부」는 재고 팩 낱말로 만들면 CNT_JOB_YN이지만 공식 용어는 HNWK_YN (R2 11/9 확인)
    official = load_official_standard()
    column = _col("C1", "수작업여부", "cnt_job_yn", SqlType.CHAR, 1)
    review = check_standard_compliance(
        _design(column), official=official, words=pack_words("inventory"),
        severities=SEVERITIES, profile="strict",
    )  # fmt: skip
    assert _codes(review) == ["SC-05"]
    assert "CNT_JOB_YN ≠ 공식 HNWK_YN" in review["findings"][0].evidence[0].quote
    assert review["requires_manual_review"]
    assert _item(review, "SC-06") == (1, 1, 0, 1)  # 여부C1 = strict char(1)


def test_real_clashing_official_term_is_undiagnosed() -> None:
    column = _col("C1", "사업자명", "bzmn_nm", SqlType.VARCHAR, 300)
    review = check_standard_compliance(
        _design(column), official=load_official_standard(), words=pack_words("inventory"),
        severities=SEVERITIES, profile="strict",
    )  # fmt: skip
    assert "SC-05" not in _codes(review) and "SC-06" not in _codes(review)
    assert _item(review, "SC-05")[1:3] == (0, 1)


# ── 끝까지: 실제 예시 설계 → 정리 → 검사 ─────────────────────────────


def _normalized_example(source_id: str) -> DesignState:
    [example] = [
        e for e in load_examples("inventory", "A03", A03Output) if e.source_id == source_id
    ]
    requirements = tuple(
        Requirement(
            id=r["id"],
            source_ref={"file_format": "csv", "row": n + 2},
            text=r["text"],
            draft_text=r["text"],
            type=r["type"],
            nfr_category=r["nfr_category"],
            analysis_version=1,
        )
        for n, r in enumerate(example.input["requirements"])
    )
    functions = tuple(
        Function.model_validate(
            {**f, "priority": None, "priority_source": "unspecified", "priority_rationale": None}
        )
        for f in example.input["functions"]
    )
    version = str(read_yaml(DEFAULT_PACK_ROOT / "inventory" / "manifest.yaml")["version"])
    design = DesignState(
        run_id="run-1",
        requirements=requirements,
        functions=functions,
        entities=_with_ids(example.output.entities, "inventory"),
        versions=VersionInfo(pack_id="inventory", pack_version=version),
    )
    result = normalize_design(design)
    assert isinstance(result, Normalized)
    return design.evolve(normalized=result.model)


@pytest.mark.parametrize("source_id", ["SFR-201", "SFR-206"])
def test_real_inventory_examples_pass_after_normalization(source_id: str) -> None:
    review = check_standard_compliance(
        _normalized_example(source_id), official=load_official_standard(),
        words=pack_words("inventory"), severities=compliance_severities(), profile="strict",
    )  # fmt: skip
    assert review["findings"] == ()
    assert not review["requires_manual_review"]
    by_code = {i.code: i for i in review["items"]}
    assert by_code["SC-01"].total > 0
    assert by_code["SC-02"].diagnosed == by_code["SC-02"].total
    assert by_code["SC-05"].diagnosed > 0  # 공식 용어와 이름이 같은 칸이 있다


# ── 이름 나누기 (RATIONALE.md: 끝에서부터, 긴 단어 먼저) ─────────────────


@pytest.mark.parametrize(
    ("name", "words", "expected"),
    [
        # 조각 수가 같으면 앞 조각을 길게 잡는 물리명 분할(가산금+리)과 결과가 다르다
        ("가산금리", {"가산금", "리", "가산", "금리"}, ("가산", "금리")),
        # 긴 단어가 있으면 「번호」로 먼저 쪼개지 않는다
        ("주민등록번호", {"주민등록번호", "등록", "번호"}, ("주민등록번호",)),
        # 가장 긴 끝 단어(나다)를 잡으면 앞(가)이 안 풀려, 한 단계 짧은 끝 단어(다)로 다시 맞춘다
        ("가나다", {"나다", "가나", "다"}, ("가나", "다")),
        ("배송지 구분코드", {"배송지", "구분", "코드"}, ("배송지", "구분", "코드")),
        ("가나라", {"가", "나"}, None),
    ],
)
def test_names_split_from_the_end_with_longer_words_first(
    name: str, words: set[str], expected: tuple[str, ...] | None
) -> None:
    assert split_from_end(name, words) == expected


def test_real_name_split_differently_by_the_physical_name_rule_is_not_a_missing_classifier() -> (
    None
):
    # 공식 용어 가산금리 = ADTN_IRT(가산+금리). 앞 조각 우선이면 가산금+리로 나뉘어 끝 단어 「리」가
    # 분류어가 아니라는 SC-02가 잘못 나온다 (검토 지적)
    column = _col("C1", "가산금리", "adtn_irt", SqlType.NUMERIC, precision=5, scale=2)
    review = check_standard_compliance(
        _design(column), official=load_official_standard(), words=pack_words("inventory"),
        severities=SEVERITIES, profile="strict",
    )  # fmt: skip
    assert review["findings"] == ()
    assert _item(review, "SC-02") == (1, 1, 0, 1)
    assert _item(review, "SC-03") == (1, 1, 0, 1)  # 금리 = 율 분류, numeric
    assert _item(review, "SC-06") == (1, 1, 0, 1)  # 율N5,2 = numeric(5,2)


def test_very_long_names_split_without_recursion_limits() -> None:
    # 재귀로 나누면 1,000글자 남짓에서 RecursionError가 난다 (검토 지적). 반복문이라 괜찮다.
    assert split_from_end("가" * 5000, {"가"}) == ("가",) * 5000
    assert split_from_end("가" * 5000 + "나", {"가"}) is None
    assert split_from_end("가나" * 2000, {"가", "나", "가나"}) == ("가나",) * 2000


@pytest.mark.parametrize(
    ("data_type", "length", "findings", "sc06"),
    [
        # SC-03이 난 칸은 SC-06 지적을 다시 내지 않지만, 도메인과 다르니 SC-06도 부적합으로 센다
        (SqlType.VARCHAR, 10, ["SC-03"], (1, 1, 0, 0)),
        (SqlType.CHAR, 10, ["SC-06"], (1, 1, 0, 0)),
        (SqlType.CHAR, 8, [], (1, 1, 0, 1)),
    ],
)
def test_sc06_counts_a_column_skipped_because_of_sc03_as_not_compliant(
    data_type: SqlType, length: int, findings: list[str], sc06: tuple[int, int, int, int]
) -> None:
    review = _check(_col("C1", "배정일자", "altmnt_ymd", data_type, length))
    assert _codes(review) == findings
    assert _item(review, "SC-06") == sc06
    [item] = [i for i in review["items"] if i.code == "SC-06"]
    assert item.rate == (100.0 if sc06[3] else 0.0)


# ── 공식 용어는 약어 경계로 나누기 (#247 리뷰) ──────────────────────────


@pytest.mark.parametrize(
    ("name", "abbreviation", "index", "expected"),
    [
        ("보고서명", "RPTP_NM", {"RPTP": ("보고서",), "NM": ("명",)}, ("보고서", "명")),
        # 한 약어를 여러 낱말이 쓰면 앞 조각부터 긴 낱말을 먼저 잡는다(가+나다가 아니라 가나+다)
        ("가나다", "AB_C", {"AB": ("가", "가나"), "C": ("다", "나다")}, ("가나", "다")),
        # 조각이 셋 이상이어도 앞 조각부터 긴 낱말이다(쓴 글자 수가 긴 a+bcd+ef가 아니다)
        ("abcdef", "A_B_C", {"A": ("ab", "a"), "B": ("c", "bcd"), "C": ("def", "ef")},
         ("ab", "c", "def")),
        # 앞 조각을 길게 잡으면 끝까지 안 맞을 때만 짧게 잡는다
        ("abcd", "A_B", {"A": ("abc", "ab"), "B": ("cd",)}, ("ab", "cd")),
        ("관할 세무서명", "CMPTNC_TXOFC_NM",
         {"CMPTNC": ("관할",), "TXOFC": ("세무서",), "NM": ("명",)}, ("관할", "세무서", "명")),
        ("보고서명", "RPTP_NM", {"RPTP": ("보고",), "NM": ("명",)}, None),  # 약어와 이름이 안 맞음
        ("보고서명", "RPTP", {"RPTP": ("보고서",)}, None),  # 이름이 남음
    ],
)  # fmt: skip
def test_official_term_names_split_on_the_abbreviation_boundaries(
    name: str,
    abbreviation: str,
    index: dict[str, tuple[str, ...]],
    expected: tuple[str, ...] | None,
) -> None:
    assert split_by_abbreviation(name, abbreviation, index) == expected


@pytest.mark.parametrize(
    ("name", "physical", "data_type", "length"),
    [
        ("보고서명", "rptp_nm", SqlType.VARCHAR, 256),  # 끝에서부터면 보고+서명
        ("영업소명", "bizofc_nm", SqlType.VARCHAR, 100),  # 영업+소명
        ("세무서명", "txofc_nm", SqlType.VARCHAR, 300),  # 세무+서명
        ("외국인수", "frgnr_cnt", SqlType.NUMERIC, None),  # 외국+인수
    ],
)
def test_names_equal_to_official_terms_are_not_missing_a_classifier(
    name: str, physical: str, data_type: SqlType, length: int | None
) -> None:
    extra = {"precision": 10, "scale": 0} if data_type is SqlType.NUMERIC else {}
    column = _col("C1", name, physical, data_type, length, **extra)
    review = check_standard_compliance(
        _design(column), official=load_official_standard(), words=pack_words("inventory"),
        severities=SEVERITIES, profile="strict",
    )  # fmt: skip
    assert review["findings"] == ()
    assert _item(review, "SC-02") == (1, 1, 0, 1)
    assert _item(review, "SC-03") == (1, 1, 0, 1)  # 분류어(명·수)로 도메인 타입까지 진단된다


def test_every_official_term_splits_on_its_abbreviation_with_a_classifier_last_word() -> None:
    # 리뷰 재현: 끝에서부터만 나누면 공식 용어 21개가 「분류어가 아닌 끝 단어」로 나뉘었다.
    # 나누기 실패도 따로 모아 본다(실패를 빼고 세면 「모두 정상 분리」를 보장하지 못한다).
    official = load_official_standard()
    index: dict[str, list[str]] = {}
    for word, info in official.words.items():
        index.setdefault(info.abbreviation.upper(), []).append(word)
    unsplit: list[str] = []
    wrong: list[str] = []
    for name, term in official.terms.items():
        parts = split_by_abbreviation(name, term.abbreviation, index)
        if parts is None:
            unsplit.append(name)
            continue
        last = official.words.get(parts[-1])
        if last is None or not last.is_classifier:
            wrong.append(name)
    assert unsplit == []
    assert wrong == []
    assert len(official.terms) > 13_000


def test_critical_sc_severity_is_rejected_when_read(tmp_path: Path) -> None:
    # ADR-0010 SC 예외: SC에 critical을 쓰면 SC 지적 하나로 최종 승인이 막힌다
    shutil.copytree(DEFAULT_PACK_ROOT / "common", tmp_path / "common")
    rules = tmp_path / "common" / "rules.yaml"
    text = rules.read_text(encoding="utf-8")
    old = "{ id: SC-01, name: unregistered_word,          severity: minor,"
    assert old in text
    # informational의 minor 제한과 별개로 SC critical 자체를 거절하는지 검사한다.
    changed = text.replace(old, old.replace("minor", "critical"))
    changed = changed.replace(
        "severity: critical, target_stage: null, handling: informational",
        "severity: critical, target_stage: null, handling: manual",
    )
    rules.write_text(changed, encoding="utf-8")
    with pytest.raises(ValueError, match=r"critical을 쓰지 않습니다.*SC-01"):
        compliance_severities(root=tmp_path)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("쨔쨔미등록 패스 코드", "forbidden_word:패스"),
        ("쨔쨔미등록 루트 코드", "synonym:루트"),
    ],
)
def test_partial_unknown_name_retains_explicit_word_diagnostics(name, kind):
    review = _check(_col("C1", name, "c_technical", SqlType.VARCHAR, 10))
    assert "SC-01" in _codes(review)
    assert any(f.kind == kind for f in review["findings"])
    assert review["requires_manual_review"] is kind.startswith("forbidden")


def test_partial_unknown_name_does_not_guess_forbidden_substrings():
    review = _check(_col("C1", "쨔쨔패스미등록 코드", "c_technical", SqlType.VARCHAR, 10))
    assert not any(f.rule_code == "SC-04" for f in review["findings"])
    assert _item(review, "SC-04")[1] == 0


def test_partial_unknown_name_keeps_explicit_pack_exemption():
    review = _check(_col("C1", "쨔쨔미등록 장부 코드", "c_technical", SqlType.VARCHAR, 10))
    assert not any(f.rule_code == "SC-04" for f in review["findings"])
