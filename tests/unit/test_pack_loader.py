import re
import shutil
import time
from pathlib import Path
from unicodedata import normalize

import pytest
import yaml

from specton.packs.build import BuildError, build
from specton.packs.loader import (
    Domain,
    PackError,
    PgType,
    PostgresMapping,
    available_packs,
    load_common,
    load_manifest,
    load_pack,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

MANIFEST = """\
name: {name}
version: 0.1.0
description: 시험용 팩
source: 합성 자료
origin: synthetic
status: draft
"""

NAMING = """\
physical_name: { dictionary_case: upper_snake, ddl_case: lower, word_separator: "_", max_bytes: 63 }
abbreviation: { case: upper, min_length: 2, max_length: 6 }
term: { classifier_last: true, max_words: null, official_term_immutable: true }
table: { prefix: null, form: null, junction_name: null }
column: { primary_key: null, foreign_key: null, self_reference_prefix: null }
type_profile: strict
reserved_words_source: postgresql_18_sql_key_words
"""

RULES = """\
rules:
  - { id: RULE-01, name: id_reference_validity, severity: critical, target_stage: null }
standard_compliance:
  checks:
    - { id: SC-01, name: unregistered_word, severity: null, target_stage: null }
  compliance_rate: compliant_columns / diagnosed_columns * 100
crud_exemption_reasons:
  soft_delete: [D]
"""

WORD = {
    "word": "설비",
    "abbreviation": "EQPM",
    "english": "Equipment",
    "definition": "필요한 시설",
    "is_classifier": True,
    "domain_group": "설비",
    "synonyms": [],
    "forbidden_synonyms": [],
}

CLASSIFIER_WORD = {
    "word": "명",
    "abbreviation": "NM",
    "english": "Name",
    "definition": "부르는 말",
    "is_classifier": True,
    "domain_group": "명",
    "synonyms": [],
    "forbidden_synonyms": [],
}

DOMAIN = {
    "group": "명칭",
    "class": "명",
    "name": "명V200",
    "standard_type": "VARCHAR",
    "length": 200,
    "scale": None,
    "storage_format": None,
    "allowed_values": None,
    "postgres": {
        "strict": {"type": "varchar", "length": 200},
        "pg_native": {"type": "varchar", "length": 200},
    },
}


def make_pack(root: Path, folder: str, text: str | None = None) -> None:
    (root / folder).mkdir(parents=True)
    (root / folder / "manifest.yaml").write_text(text or MANIFEST.format(name=folder), "utf-8")


def make_common(
    root: Path, *, status: str = "draft", naming: str = NAMING, rules: str = RULES
) -> None:
    make_pack(root, "common", MANIFEST.format(name="common").replace("draft", status))
    (root / "common/words.yaml").write_text(
        yaml.safe_dump({"edition": "test", "words": [WORD, CLASSIFIER_WORD]}, allow_unicode=True),
        "utf-8",
    )
    (root / "common/domains.yaml").write_text(
        yaml.safe_dump(
            {
                "edition": "test",
                "allowed_sql_types": ["varchar"],
                "domains": [DOMAIN],
                "on_unknown": "finding",
            },
            allow_unicode=True,
        ),
        "utf-8",
    )
    (root / "common/naming.yaml").write_text(naming, "utf-8")
    (root / "common/rules.yaml").write_text(rules, "utf-8")


def make_full_pack(root: Path, pack: str) -> None:
    make_pack(root, pack)
    (root / pack / "words.yaml").write_text(yaml.safe_dump({"words": []}), "utf-8")
    (root / pack / "terms.yaml").write_text(
        yaml.safe_dump(
            {
                "terms": [
                    {
                        "term": "설비명",
                        "composition": ["설비", "명"],
                        "domain": "명V200",
                        "physical_name": "EQPM_NM",
                        "source": "official",
                        "synonyms": [],
                    }
                ]
            },
            allow_unicode=True,
        ),
        "utf-8",
    )
    (root / pack / "patterns.yaml").write_text(
        yaml.safe_dump(
            {
                "patterns": [
                    {
                        "id": "P-X-01",
                        "name": "sample",
                        "when": "항상",
                        "suggests": {"attribute": "USE_YN"},
                        "source": "test",
                    }
                ]
            },
            allow_unicode=True,
        ),
        "utf-8",
    )


def test_available_packs_skips_common_and_folders_without_manifest(tmp_path: Path) -> None:
    make_pack(tmp_path, "common")
    make_pack(tmp_path, "inventory")
    make_pack(tmp_path, "maintenance")
    (tmp_path / "sources").mkdir()

    assert available_packs(root=tmp_path) == ("inventory", "maintenance")


def test_load_manifest_reads_name_and_version(tmp_path: Path) -> None:
    make_pack(tmp_path, "inventory")

    manifest = load_manifest("inventory", root=tmp_path)

    assert (manifest.name, manifest.version, manifest.status) == ("inventory", "0.1.0", "draft")


def test_load_manifest_rejects_name_different_from_folder(tmp_path: Path) -> None:
    make_pack(tmp_path, "inventory", MANIFEST.format(name="maintenance"))

    with pytest.raises(PackError, match="폴더 이름"):
        load_manifest("inventory", root=tmp_path)


@pytest.mark.parametrize("pack", ["../inventory", "Inventory", "", "inv/../x"])
def test_load_manifest_rejects_names_that_are_not_pack_names(tmp_path: Path, pack: str) -> None:
    with pytest.raises(PackError, match="영문 소문자"):
        load_manifest(pack, root=tmp_path)


def test_load_manifest_rejects_missing_pack(tmp_path: Path) -> None:
    with pytest.raises(PackError, match="팩이 없습니다"):
        load_manifest("inventory", root=tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("version", "0.1"), ("status", "final"), ("origin", "unknown"), ("description", "''")],
)
def test_load_manifest_rejects_bad_values(tmp_path: Path, field: str, value: str) -> None:
    text = MANIFEST.format(name="inventory").replace(
        next(line for line in MANIFEST.splitlines() if line.startswith(field)),
        f"{field}: {value}",
    )
    make_pack(tmp_path, "inventory", text)

    with pytest.raises(PackError, match="형식이 틀렸습니다"):
        load_manifest("inventory", root=tmp_path)


def test_repository_packs_load() -> None:
    root = REPO_ROOT / "domain_packs"

    assert available_packs(root=root) == ("inventory", "maintenance")
    for pack in (*available_packs(root=root), "common"):
        assert load_manifest(pack, root=root).name == pack


# --- 공통 팩 모델 (task 1) ---


def test_load_common_reads_words_domains_naming_rules(tmp_path: Path) -> None:
    make_common(tmp_path)

    common = load_common(root=tmp_path)

    assert [w.word for w in common.words] == ["설비", "명"]
    assert common.domains[0].name == "명V200"
    assert common.domains[0].domain_class == "명"
    assert common.domains[0].postgres.strict.type == "varchar"
    assert common.naming.type_profile == "strict"
    assert common.rules.rules[0].id == "RULE-01"
    assert common.rules.crud_exemption_reasons == {"soft_delete": ("D",)}


def test_real_common_pack_loads_as_is() -> None:
    common = load_common(root=REPO_ROOT / "domain_packs")

    assert common.manifest.name == "common"
    assert len(common.words) > 0
    assert len(common.domains) > 0


def test_real_common_naming_has_decided_values() -> None:
    """R4 초안(#11, 2026-11-05)으로 정한 값이 실제 naming.yaml에 반영됐는지 확인한다."""
    common = load_common(root=REPO_ROOT / "domain_packs")
    naming = common.naming

    assert naming.term.max_words == "unlimited"
    assert naming.table.prefix == "none"
    assert naming.table.form == "as_dictionary"
    assert naming.table.junction_name == "parent_child"
    assert naming.column.primary_key == "term_physical_name"
    assert naming.column.foreign_key == "parent_key_physical_name"
    assert naming.column.self_reference_prefix == "상위"


# --- 팩 모델 (task 2) ---


def test_load_pack_reads_terms_words_patterns(tmp_path: Path) -> None:
    make_common(tmp_path)
    make_full_pack(tmp_path, "inventory")

    pack = load_pack("inventory", root=tmp_path)

    assert pack.terms[0].term == "설비명"
    assert pack.terms[0].physical_name == "EQPM_NM"
    assert pack.words == ()
    assert pack.patterns[0].id == "P-X-01"
    assert pack.patterns[0].suggests == {"attribute": "USE_YN"}


@pytest.mark.parametrize(
    "missing",
    [
        "inventory/terms.yaml",
        "inventory/patterns.yaml",
        "inventory/words.yaml",
        "common/words.yaml",
    ],
)
def test_missing_pack_file_is_a_pack_error(tmp_path: Path, missing: str) -> None:
    """필수 팩 파일이 없으면 FileNotFoundError가 아니라 PackError로 알린다 (#132 R1 리뷰)."""
    make_common(tmp_path)
    make_full_pack(tmp_path, "inventory")
    (tmp_path / missing).unlink()

    with pytest.raises(PackError, match="읽지 못했습니다"):
        load_pack("inventory", root=tmp_path)


def test_real_inventory_and_maintenance_packs_load() -> None:
    root = REPO_ROOT / "domain_packs"

    for name in ("inventory", "maintenance"):
        pack = load_pack(name, root=root)
        assert len(pack.terms) > 0
        assert all(t.domain for t in pack.terms)


def test_term_with_domain_not_in_common_is_rejected(tmp_path: Path) -> None:
    make_common(tmp_path)
    make_full_pack(tmp_path, "inventory")
    terms_path = tmp_path / "inventory/terms.yaml"
    data = yaml.safe_load(terms_path.read_text("utf-8"))
    data["terms"][0]["domain"] = "없는도메인"
    terms_path.write_text(yaml.safe_dump(data, allow_unicode=True), "utf-8")

    with pytest.raises(PackError, match="없는도메인"):
        load_pack("inventory", root=tmp_path)


# --- 미정값(null) 규칙 (task 3) ---


def test_draft_common_allows_blank_naming_and_rules(tmp_path: Path) -> None:
    make_common(tmp_path, status="draft")

    common = load_common(root=tmp_path)

    assert common.naming.term.max_words is None
    assert common.rules.rules[0].target_stage is None


def test_approved_common_rejects_blank_naming_and_rules(tmp_path: Path) -> None:
    make_common(tmp_path, status="approved")

    with pytest.raises(PackError, match="미정값") as exc:
        load_common(root=tmp_path)

    message = str(exc.value)
    assert "term.max_words" in message
    assert "rules.RULE-01.target_stage" in message
    assert "standard_compliance.SC-01.severity" in message


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (
            "table: { prefix: null, form: null, junction_name: null }",
            "table: { prefix: null, form: plural_auto, junction_name: null }",
        ),
        (
            "column: { primary_key: null, foreign_key: null, self_reference_prefix: null }",
            "column: { primary_key: id, foreign_key: null, self_reference_prefix: null }",
        ),
        (  # 아직 정하지 않은 값도 naming.py가 모르면 거절한다 (허용 값 목록은 한 곳과 똑같이 둔다)
            "table: { prefix: null, form: null, junction_name: null }",
            "table: { prefix: TB_, form: singular, junction_name: null }",
        ),
        (
            "term: { classifier_last: true, max_words: null, official_term_immutable: true }",
            "term: { classifier_last: true, max_words: 5, official_term_immutable: true }",
        ),
    ],
)
def test_naming_rejects_unknown_value_names(tmp_path: Path, path: str, bad_value: str) -> None:
    """정해 둔 값 이름(Literal) 밖의 값은 거절한다 — 예: `form: plural_auto`, `primary_key: id`."""
    naming = NAMING.replace(path, bad_value)
    make_common(tmp_path, naming=naming)

    with pytest.raises(PackError, match="형식이 틀렸습니다"):
        load_common(root=tmp_path)


@pytest.mark.parametrize(
    ("filled", "blank", "path"),
    [
        ("junction_name: parent_child", "junction_name: null", "table.junction_name"),
        (
            "self_reference_prefix: 상위",
            "self_reference_prefix: null",
            "column.self_reference_prefix",
        ),
    ],
)
def test_approved_common_reports_each_new_blank_key(
    tmp_path: Path, filled: str, blank: str, path: str
) -> None:
    """나머지는 채웠지만 새 키 하나만 null이면 approved에서 미정값으로 걸린다."""
    make_common(
        tmp_path, status="approved", naming=FILLED_NAMING.replace(filled, blank), rules=FILLED_RULES
    )

    with pytest.raises(PackError, match="미정값") as exc:
        load_common(root=tmp_path)

    assert path in str(exc.value)


def test_domain_also_constructs_by_field_name_not_only_alias() -> None:
    """`class`는 별칭이고 필드 이름은 `domain_class`다. 생성자에서 필드 이름으로도 써야 한다."""
    pg = PgType(type="varchar", length=200)
    domain = Domain(
        group="명칭",
        domain_class="명",
        name="명V200",
        standard_type="VARCHAR",
        length=200,
        scale=None,
        storage_format=None,
        allowed_values=None,
        postgres=PostgresMapping(strict=pg, pg_native=pg),
    )

    assert domain.domain_class == "명"


def test_rule_missing_target_stage_key_is_rejected(tmp_path: Path) -> None:
    """미정값은 null을 적어야 한다. 키 자체가 빠지면(실수로 빼먹은 것과 구분 못 함) 거절한다."""
    rules_missing_key = """\
rules:
  - { id: RULE-01, name: id_reference_validity, severity: critical }
standard_compliance:
  checks:
    - { id: SC-01, name: unregistered_word, severity: null, target_stage: null }
  compliance_rate: compliant_columns / diagnosed_columns * 100
crud_exemption_reasons:
  soft_delete: [D]
"""
    make_common(tmp_path, rules=rules_missing_key)

    with pytest.raises(PackError, match="형식이 틀렸습니다"):
        load_common(root=tmp_path)


FILLED_NAMING = """\
physical_name: { dictionary_case: upper_snake, ddl_case: lower, word_separator: "_", max_bytes: 63 }
abbreviation: { case: upper, min_length: 2, max_length: 6 }
term: { classifier_last: true, max_words: unlimited, official_term_immutable: true }
table: { prefix: none, form: as_dictionary, junction_name: parent_child }
column: { primary_key: term_physical_name, foreign_key: parent_key_physical_name,
  self_reference_prefix: 상위 }
type_profile: strict
reserved_words_source: postgresql_18_sql_key_words
"""

FILLED_RULES = """\
rules:
  - { id: RULE-01, name: id_reference_validity, severity: critical, target_stage: requirements }
standard_compliance:
  checks:
    - { id: SC-01, name: unregistered_word, severity: minor, target_stage: requirements }
  compliance_rate: compliant_columns / diagnosed_columns * 100
crud_exemption_reasons:
  soft_delete: [D]
"""


@pytest.mark.parametrize("empty", ['""', '"  "'], ids=["empty", "spaces"])
def test_approved_common_rejects_empty_self_reference_prefix(tmp_path: Path, empty: str) -> None:
    """approved에서는 빈 문자열·공백만 있는 접두어도 미정값이다 (#166 R1 리뷰, #151 기준).

    다른 값은 모두 채우고 이 칸만 비워, 다른 미정값 때문에 걸리는 것과 구분한다.
    """
    naming = FILLED_NAMING.replace("self_reference_prefix: 상위", f"self_reference_prefix: {empty}")
    make_common(tmp_path, status="approved", naming=naming, rules=FILLED_RULES)

    with pytest.raises(PackError, match="미정값") as exc:
        load_common(root=tmp_path)

    assert "column.self_reference_prefix" in str(exc.value)


@pytest.mark.parametrize("empty", ['""', '"  "'], ids=["empty", "spaces"])
def test_draft_common_allows_empty_self_reference_prefix(tmp_path: Path, empty: str) -> None:
    """draft에서는 빈 문자열·공백도 지금처럼 받아 준다(미정값 허용 유지).

    공백만 있는 값은 `str_strip_whitespace`로 읽을 때 빈 문자열이 된다.
    """
    naming = FILLED_NAMING.replace("self_reference_prefix: 상위", f"self_reference_prefix: {empty}")
    make_common(tmp_path, status="draft", naming=naming, rules=FILLED_RULES)

    common = load_common(root=tmp_path)

    assert common.naming.column.self_reference_prefix == ""


def test_approved_common_with_all_values_filled_passes(tmp_path: Path) -> None:
    make_common(tmp_path, status="approved", naming=FILLED_NAMING, rules=FILLED_RULES)

    common = load_common(root=tmp_path)

    assert common.naming.term.max_words == "unlimited"
    assert common.rules.standard_compliance.checks[0].severity == "minor"


# --- load_pack 전체 (task 4) ---


def test_load_pack_rejects_common() -> None:
    with pytest.raises(PackError, match="선택할 수 있는 팩이 아닙니다"):
        load_pack("common", root=REPO_ROOT / "domain_packs")


@pytest.mark.parametrize("pack", ["../inventory", "Inventory", ""])
def test_load_pack_rejects_path_traversal_names(pack: str) -> None:
    with pytest.raises(PackError, match="영문 소문자"):
        load_pack(pack, root=REPO_ROOT / "domain_packs")


def test_load_inventory_pack_timing() -> None:
    """참고용 측정: 공통 words.yaml(~4,875줄)을 포함한 inventory 적재 시간을 출력한다."""
    root = REPO_ROOT / "domain_packs"

    start = time.perf_counter()
    load_pack("inventory", root=root)
    elapsed = time.perf_counter() - start

    print(f"load_pack('inventory') 적재 시간: {elapsed:.4f}초")
    assert elapsed < 5.0


# --- NFC·공백으로 같아지는 용어 이름 (#264) ---


def nfd(text: str) -> str:
    converted = normalize("NFD", text)
    assert converted != text  # 시험 입력이 정말 NFD인지 먼저 확인
    return converted


def write_terms(root: Path, pack: str, terms: list[dict[str, object]]) -> None:
    """빌드를 거치지 않은 사용자 지정 팩처럼 terms.yaml을 직접 쓴다."""
    (root / pack / "terms.yaml").write_text(
        yaml.safe_dump({"terms": terms}, allow_unicode=True), "utf-8"
    )


def term(name: str, physical: str, synonyms: list[str] | None = None) -> dict[str, object]:
    return {
        "term": name,
        "composition": ["설비", "명"],
        "domain": "명V200",
        "physical_name": physical,
        "source": "project",
        "synonyms": synonyms or [],
    }


@pytest.mark.parametrize(
    ("terms", "message"),
    [
        ([term("설비명", "EQPM_NM"), term(nfd("설비명"), "EQPM_NM")], "NFC·NFD\\)만 다른"),
        ([term("설비명", "EQPM_NM"), term(nfd("설비명"), "EQPM_OTHER_NM")], "NFC·NFD\\)만 다른"),
        ([term("설비명", "EQPM_NM"), term("설비명", "EQPM_NM")], "완전히 같은 문자열"),
        # 모델은 둘 다 '설비명'으로 읽지만 원본으로 검사해 공백 원인을 알린다
        ([term("설비명", "EQPM_NM"), term(" 설비명", "EQPM_OTHER_NM")], "앞뒤 공백만 다른"),
        (
            [term("설비명", "EQPM_NM"), term("장비명", "EQUIP_NM", [nfd("설비명")])],
            "동의어 .*다른 정식 용어 '설비명'",
        ),
    ],
)
def test_load_pack_rejects_term_name_conflicts_from_custom_root(
    tmp_path: Path, terms: list[dict[str, object]], message: str
) -> None:
    make_common(tmp_path)
    make_full_pack(tmp_path, "inventory")
    write_terms(tmp_path, "inventory", terms)

    with pytest.raises(PackError, match=message):
        load_pack("inventory", root=tmp_path)


def test_load_pack_allows_synonym_equal_to_own_name(tmp_path: Path) -> None:
    make_common(tmp_path)
    make_full_pack(tmp_path, "inventory")
    write_terms(tmp_path, "inventory", [term("설비명", "EQPM_NM", [nfd("설비명"), " 설비명"])])

    pack = load_pack("inventory", root=tmp_path)

    assert pack.terms[0].synonyms == (
        nfd("설비명"),
        "설비명",
    )  # NFC는 바꾸지 않는다 (공백은 모델이 원래 뺌)


def copy_real_packs(tmp_path: Path) -> Path:
    root = tmp_path / "domain_packs"
    shutil.copytree(REPO_ROOT / "domain_packs", root)
    return root


def conflict_variants(first: str, second: str) -> list[tuple[str, str, str | None]]:
    """(설명, 둘째 용어에 덮어쓸 이름, 둘째 용어에 더할 동의어). 이름이 None이면 이름은 그대로."""
    return [
        ("exact", first, None),
        ("nfd", nfd(first), None),
        ("space", f" {first}", None),
        ("space_nfd", f" {nfd(first)}", None),
        ("synonym", second, nfd(first)),
        ("own_synonym", second, nfd(second)),  # 충돌 아님
        ("shared_synonym", second, "__shared__"),  # 충돌 아님
    ]


@pytest.mark.parametrize("variant", range(7))
def test_build_and_loader_agree_on_real_pack_copy(tmp_path: Path, variant: int) -> None:
    """같은 용어 목록을 빌드 입력·로더 입력 양쪽에 넣으면 같은 판정을 낸다 (사용자 지정 경로)."""
    root = copy_real_packs(tmp_path)
    folder = root / "inventory"
    specs_doc = yaml.safe_load((folder / "term_specs.yaml").read_text("utf-8"))
    terms_doc = yaml.safe_load((folder / "terms.yaml").read_text("utf-8"))
    first, second = (t["term"] for t in specs_doc["terms"][:2])
    _, name, synonym = conflict_variants(first, second)[variant]
    for doc in (specs_doc, terms_doc):
        target = doc["terms"][1]
        target["term"] = name
        if synonym == "__shared__":
            shared = doc["terms"][0]["synonyms"][0]
            target["synonyms"] = [*target["synonyms"], shared]
        elif synonym is not None:
            target["synonyms"] = [*target["synonyms"], synonym]
    (folder / "term_specs.yaml").write_text(yaml.safe_dump(specs_doc, allow_unicode=True), "utf-8")
    (folder / "terms.yaml").write_text(yaml.safe_dump(terms_doc, allow_unicode=True), "utf-8")
    manifest = folder / "manifest.yaml"
    # 내용이 바뀐 사본이라 version을 올려 lock 거절을 피한다. 현재 버전 값에 묶이지 않게 한다.
    text, count = re.subn(r"(?m)^version: .+$", "version: 9.9.9", manifest.read_text("utf-8"))
    assert count == 1
    manifest.write_text(text, "utf-8")

    build_problem = load_problem = None
    try:
        build(root)
    except BuildError as exc:
        build_problem = str(exc).split("\n", 1)[1]
    try:
        load_pack("inventory", root=root)
    except PackError as exc:
        load_problem = str(exc).split("\n", 1)[1]

    # 경로 줄을 뺀 문제 메시지가 원인 안내까지 완전히 같다. 로더 모델은 앞뒤 공백을 지우지만
    # 로더는 원본 값으로 검사하므로 공백 차이도 빌드와 같은 원인으로 알린다.
    assert build_problem == load_problem
    assert (build_problem is None) == (variant >= 5)
