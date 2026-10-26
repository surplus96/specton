from pathlib import Path

import pytest
import yaml

from specton.contracts.base import SqlType
from specton.packs.build import BuildError, build, check, write

REPO_ROOT = Path(__file__).resolve().parents[2]

REVISION_COLUMNS = ["제정차수", "개정구분명(폐기 또는 변경)", "개정항목", "개정사유"]


def header(*columns: str) -> str:
    return "﻿" + ",".join([*columns, *REVISION_COLUMNS]) + "\n"


WORDS_CSV = (
    header(
        "공통표준단어명",
        "공통표준단어영문약어명",
        "공통표준단어 영문명",
        "공통표준단어 설명",
        "형식단어여부",
        "공통표준도메인분류명",
        "이음동의어 목록",
        "금칙어 목록",
    )
    + """설비,EQPM,Equipment,設備. 필요한 시설,N,,,,1차,,,
코드,CD,Code,Code. 기호 체계,Y,코드,,,1차,,,
명,NM,Name,名. 부르는 말,Y,명,"이름, 명칭",,1차,,,
상태,STTS,Status,狀態. 형편,N,,,,1차,,,
폐기단어,OLD,Old,옛 단어,N,,,,1차,폐기,,
"""
)

DOMAINS_CSV = (
    header(
        "공통표준도메인그룹명",
        "공통표준도메인분류명",
        "공통표준도메인명",
        "공통표준도메인설명",
        "데이터타입",
        "데이터길이",
        "데이터소수점길이",
        "저장형식",
        "표현형식",
        "단위",
        "허용값",
    )
    + """코드,코드,코드C10,코드,CHAR,10,,10자리 문자,,,,1차,,,
명칭,명,명V200,명,VARCHAR,200,,200자리 이내 문자,,,,1차,,,
"""
)

TERMS_CSV = (
    header(
        "공통표준용어명",
        "공통표준용어설명",
        "공통표준용어영문약어명",
        "공통표준도메인명",
        "허용값",
        "저장 형식",
        "표현 형식",
        "행정표준코드명",
        "소관기관명",
        "용어 이음동의어 목록",
    )
    + """설비명,설비 이름,EQPM_NM,명V200,,,,,,,1차,,,
"""
)


def make_root(tmp_path: Path, specs: list[dict[str, object]]) -> Path:
    root = tmp_path / "domain_packs"
    (root / "sources").mkdir(parents=True)
    (root / "sources/words.csv").write_text(WORDS_CSV, encoding="utf-8")
    (root / "sources/domains.csv").write_text(DOMAINS_CSV, encoding="utf-8")
    (root / "sources/terms.csv").write_text(TERMS_CSV, encoding="utf-8")
    (root / "sources/sources.yaml").write_text(
        yaml.safe_dump(
            {
                "edition": "test edition",
                "files": {
                    "words": {"path": "words.csv"},
                    "terms": {"path": "terms.csv"},
                    "domains": {"path": "domains.csv"},
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "common").mkdir()
    pack = root / "maintenance"
    pack.mkdir()
    (pack / "words.yaml").write_text("words: []\n", encoding="utf-8")
    (pack / "term_specs.yaml").write_text(
        yaml.safe_dump({"terms": specs}, allow_unicode=True), encoding="utf-8"
    )
    return root


def spec(term: str, composition: list[str], domain: str) -> dict[str, object]:
    return {"term": term, "composition": composition, "domain": domain, "synonyms": ["별칭"]}


def load(outputs: dict[Path, str], root: Path, rel: str) -> dict[str, object]:
    data = yaml.safe_load(outputs[root / rel])
    assert isinstance(data, dict)
    return data


def test_official_term_uses_official_physical_name(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])

    outputs = build(root)

    terms = load(outputs, root, "maintenance/terms.yaml")["terms"]
    assert terms == [
        {
            "term": "설비명",
            "composition": ["설비", "명"],
            "domain": "명V200",
            "physical_name": "EQPM_NM",
            "source": "official",
            "synonyms": ["별칭"],
        }
    ]


def test_project_term_joins_word_abbreviations(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("설비상태코드", ["설비", "상태", "코드"], "코드C10")])

    terms = load(build(root), root, "maintenance/terms.yaml")["terms"]

    assert isinstance(terms, list)
    assert terms[0]["physical_name"] == "EQPM_STTS_CD"
    assert terms[0]["source"] == "project"


def test_common_words_include_used_words_and_all_classifiers(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])

    words = load(build(root), root, "common/words.yaml")["words"]

    assert isinstance(words, list)
    assert [w["word"] for w in words] == ["설비", "코드", "명"]
    assert words[0]["definition"] == "필요한 시설"  # 한자 접두어 제거
    assert words[1]["definition"] == "Code. 기호 체계"  # 영문 접두어 유지
    assert words[2]["synonyms"] == ["이름", "명칭"]


def test_common_domains_include_only_used_domains(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])

    domains = load(build(root), root, "common/domains.yaml")["domains"]

    assert isinstance(domains, list)
    assert [d["name"] for d in domains] == ["명V200"]


def test_rejects_term_not_ending_with_classifier(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("설비상태", ["설비", "상태"], "코드C10")])

    with pytest.raises(BuildError, match="분류어"):
        build(root)


def test_rejects_classifier_domain_mismatch(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("설비코드", ["설비", "코드"], "명V200")])

    with pytest.raises(BuildError, match="도메인"):
        build(root)


def test_rejects_unregistered_word(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("폐기단어명", ["폐기단어", "명"], "명V200")])

    with pytest.raises(BuildError, match="사전에 없는 단어"):
        build(root)


def test_check_detects_hand_edited_generated_file(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])
    write(build(root))
    assert check(root) == []

    terms_file = root / "maintenance/terms.yaml"
    terms_file.write_text(terms_file.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")

    assert check(root) == [terms_file]


def test_common_pack_allows_exactly_the_contract_sql_types() -> None:
    domains_file = REPO_ROOT / "domain_packs/common/domains.yaml"
    domains = yaml.safe_load(domains_file.read_text(encoding="utf-8"))

    assert domains["allowed_sql_types"] == [t.value for t in SqlType]
