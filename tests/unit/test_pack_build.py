from pathlib import Path
from unicodedata import normalize

import pytest
import yaml

from specton.contracts.base import SqlType
from specton.packs.build import LOCK_NAME, BuildError, build, check, pack_content_hash, write

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
    (root / "common/manifest.yaml").write_text("version: 0.1.0\n", encoding="utf-8")
    pack = root / "maintenance"
    pack.mkdir()
    (pack / "manifest.yaml").write_text("version: 0.1.0\n", encoding="utf-8")
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


def test_common_words_include_unused_official_words_but_not_retired_words(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])

    words = load(build(root), root, "common/words.yaml")["words"]

    assert isinstance(words, list)
    assert [w["word"] for w in words] == ["설비", "코드", "명", "상태"]
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


# --- pack.lock (task 5) ---


def test_build_writes_lock_file_per_pack(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])

    outputs = build(root)

    assert root / "common" / LOCK_NAME in outputs
    assert root / "maintenance" / LOCK_NAME in outputs
    lock = yaml.safe_load(outputs[root / "maintenance" / LOCK_NAME])
    assert list(lock["versions"]) == ["0.1.0"]
    assert len(lock["versions"]["0.1.0"]) == 64


def test_check_passes_right_after_generating(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])
    write(build(root))

    assert check(root) == []


def add_example(root: Path) -> Path:
    examples = root / "maintenance/examples"
    examples.mkdir()
    path = examples / "A01.yaml"
    path.write_text("agent: A01\nrole: x\nstatus: draft\nexamples: []\n", encoding="utf-8")
    return path


def test_check_also_rejects_content_change_without_version_bump(tmp_path: Path) -> None:
    """check도 내부에서 build를 부르므로, 다시 생성해 보지 않고 검사만 해도 같은 이유로 막힌다."""
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])
    write(build(root))
    assert check(root) == []

    add_example(root)

    with pytest.raises(BuildError, match="version"):
        check(root)


def test_build_rejects_rebuild_without_version_bump_after_content_change(tmp_path: Path) -> None:
    """예시를 바꾸고 version은 그대로 둔 채 다시 생성하면 거절한다(controller 리뷰로 찾은 구멍)."""
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])
    write(build(root))
    add_example(root)

    with pytest.raises(BuildError, match="version") as exc:
        build(root)

    assert "maintenance" in str(exc.value)
    assert "0.1.0" in str(exc.value)


def test_build_accepts_rebuild_after_version_bump_and_keeps_history(tmp_path: Path) -> None:
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])
    write(build(root))
    add_example(root)
    (root / "maintenance/manifest.yaml").write_text("version: 0.1.1\n", encoding="utf-8")

    write(build(root))

    assert check(root) == []
    lock = yaml.safe_load((root / "maintenance" / LOCK_NAME).read_text(encoding="utf-8"))
    assert set(lock["versions"]) == {"0.1.0", "0.1.1"}
    assert lock["versions"]["0.1.0"] != lock["versions"]["0.1.1"]


def test_version_bumped_without_rebuild_is_a_stale_lock(tmp_path: Path) -> None:
    """버전만 올리고 다시 생성하지 않으면 lock에 새 버전 항목이 없어 디스크와 달라진다."""
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])
    write(build(root))
    assert check(root) == []

    (root / "maintenance/manifest.yaml").write_text("version: 0.1.1\n", encoding="utf-8")

    stale = check(root)
    assert root / "maintenance" / LOCK_NAME in stale


def test_rebuild_with_same_version_and_unchanged_content_passes(tmp_path: Path) -> None:
    """내용도 버전도 그대로면 다시 생성해도 통과한다(오탐 방지)."""
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200")])
    write(build(root))

    write(build(root))

    assert check(root) == []


def test_pack_content_hash_ignores_crlf_vs_lf(tmp_path: Path) -> None:
    """줄바꿈만 LF·CRLF로 다른 팩은 해시가 같다(Windows에서 받아도 lock이 깨지지 않게).

    `write_text()`는 Windows에서 `\n`을 `\r\n`으로 바꿔 저장한다. 그러면 LF로 쓴 파일은 CRLF가 되고
    CRLF로 쓴 파일은 `\r\r\n`이 되어 의도한 비교가 되지 않으므로, `write_bytes()`로 운영체제와
    상관없이 정확한 바이트를 쓴다(R4가 Windows 실행에서 발견, #141 본문).
    """
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "a.yaml").write_bytes(b"x: 1\ny: 2\n")

    lf_hash = pack_content_hash(pack_dir)
    (pack_dir / "a.yaml").write_bytes(b"x: 1\r\ny: 2\r\n")
    crlf_hash = pack_content_hash(pack_dir)

    assert lf_hash == crlf_hash


def test_pack_content_hash_ignores_bom(tmp_path: Path) -> None:
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "a.yaml").write_text("x: 1\ny: 2\n", encoding="utf-8")

    no_bom_hash = pack_content_hash(pack_dir)
    (pack_dir / "a.yaml").write_text("x: 1\ny: 2\n", encoding="utf-8-sig")
    bom_hash = pack_content_hash(pack_dir)

    assert no_bom_hash == bom_hash


def test_pack_content_hash_ignores_lock_and_md_files(tmp_path: Path) -> None:
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "a.yaml").write_text("x: 1\n", encoding="utf-8")
    base_hash = pack_content_hash(pack_dir)

    (pack_dir / LOCK_NAME).write_text("version: 9.9.9\nsha256: deadbeef\n", encoding="utf-8")
    (pack_dir / "RATIONALE.md").write_text("무관한 내용\n", encoding="utf-8")

    assert pack_content_hash(pack_dir) == base_hash


def test_real_packs_pass_check_after_build() -> None:
    assert check(REPO_ROOT / "domain_packs") == []


# --- NFC·공백으로 같아지는 용어 이름 (#264) ---


def nfd(text: str) -> str:
    converted = normalize("NFD", text)
    assert converted != text  # 시험 입력이 정말 NFD인지 먼저 확인
    return converted


def test_nfd_duplicate_with_different_content_is_rejected(tmp_path: Path) -> None:
    """지금까지 통과하던 재현 경우: 구성이 달라 물리명이 다르면 물리명 검사에 걸리지 않았다."""
    root = make_root(
        tmp_path,
        [
            spec("설비명", ["설비", "명"], "명V200"),
            spec(nfd("설비명"), ["설비", "코드"], "코드C10"),
        ],
    )

    with pytest.raises(BuildError, match=r"용어 이름 중복 '설비명'.*NFC·NFD\)만 다른"):
        build(root)


def test_nfd_duplicate_with_same_content_is_rejected_before_physical_name(tmp_path: Path) -> None:
    root = make_root(
        tmp_path,
        [
            spec("설비상태코드", ["설비", "상태", "코드"], "코드C10"),
            spec(nfd("설비상태코드"), ["설비", "상태", "코드"], "코드C10"),
        ],
    )

    with pytest.raises(BuildError, match="용어 이름 중복") as caught:
        build(root)
    assert "물리명 중복" not in str(caught.value)  # 원인이 더 분명한 이름 충돌을 먼저 알린다


def test_exact_duplicate_name_is_rejected_as_exact(tmp_path: Path) -> None:
    root = make_root(
        tmp_path,
        [
            spec("설비상태코드", ["설비", "상태", "코드"], "코드C10"),
            spec("설비상태코드", ["설비", "코드"], "코드C10"),
        ],
    )

    with pytest.raises(BuildError, match="완전히 같은 문자열"):
        build(root)


def test_name_differing_only_by_surrounding_space_is_rejected(tmp_path: Path) -> None:
    root = make_root(
        tmp_path,
        [
            spec("설비상태코드", ["설비", "상태", "코드"], "코드C10"),
            spec(" 설비상태코드", ["설비", "코드"], "코드C10"),
        ],
    )

    with pytest.raises(BuildError, match="앞뒤 공백만 다른"):
        build(root)


def test_synonym_equal_to_another_term_is_rejected(tmp_path: Path) -> None:
    other = spec("설비상태코드", ["설비", "상태", "코드"], "코드C10")
    other["synonyms"] = [nfd("설비명")]
    root = make_root(tmp_path, [spec("설비명", ["설비", "명"], "명V200"), other])

    with pytest.raises(BuildError, match=r"동의어 .*다른 정식 용어 '설비명'"):
        build(root)


def test_synonym_equal_to_own_name_builds_and_keeps_original_strings(tmp_path: Path) -> None:
    own = spec("설비상태코드", ["설비", "상태", "코드"], "코드C10")
    own["synonyms"] = [nfd("설비상태코드"), " 설비상태코드"]
    root = make_root(tmp_path, [own])

    terms = load(build(root), root, "maintenance/terms.yaml")["terms"]

    assert isinstance(terms, list)
    assert terms[0]["synonyms"] == [
        nfd("설비상태코드"),
        " 설비상태코드",
    ]  # 비교만 하고 바꾸지 않는다
