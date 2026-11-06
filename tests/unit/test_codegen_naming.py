"""TC-N06·TC-F09 일부: 모델 정리(#12)의 팩 연결 — 실제 팩 파일에서 이름 규칙·사전을 읽는다.

기대값의 물리명(`eqpm_cd` 등)은 팩 파일(`terms.yaml`·`common/words.yaml`)에 적힌 값이다.
두 팩 실행 사례의 모양은 각 팩의 `examples/A04.yaml`(MNT-002, INV-005)을 옮겼고,
예시에 없는 길이·req_ids만 보충했다.
"""

import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

import pytest
import yaml

from specton.codegen import naming
from specton.codegen.model import Normalized, NormalizeFailed, ProblemCode
from specton.codegen.naming import (
    DEFAULT_PACK_ROOT,
    PackLexicon,
    load_naming_rules,
    load_pack_lexicon,
    physical_name,
    reserved_words,
)
from specton.codegen.normalize import PackRef, normalize
from specton.contracts import DesignState, Entity, Relationship, Requirement
from specton.packs.build import read_yaml

LEXICON_FILES = (
    "common/naming.yaml",
    "common/domains.yaml",
    "common/words.yaml",
    "{pack}/words.yaml",
    "{pack}/terms.yaml",
)


def _copy_pack(tmp_path: Path, pack: str) -> Path:
    for name in LEXICON_FILES:
        rel = name.format(pack=pack)
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DEFAULT_PACK_ROOT / rel, tmp_path / rel)
    return tmp_path


# #11 R2 답(명명 규칙 빈칸 답)에 적힌 값. 실제 naming.yaml에는 R2 후속 PR이 채운다.
# 임시(#11): 값 이름은 공통 팩 draft·ADR-0009 제안 상태라 바뀔 수 있음 (naming.py와 함께 고친다).
AGREED_NAMING = {
    ("term", "max_words"): "unlimited",
    ("table", "prefix"): "none",
    ("table", "form"): "as_dictionary",
    ("table", "junction_name"): "parent_child",
    ("column", "primary_key"): "term_physical_name",
    ("column", "foreign_key"): "parent_key_physical_name",
    ("column", "self_reference_prefix"): "상위",
}


# 위 칸을 모두 빈칸(미정)으로. 실제 팩 값과 상관없이 시험할 칸만 채우려고 먼저 덮는다.
UNSET_NAMING: dict[tuple[str, str], Any] = dict.fromkeys(AGREED_NAMING)


def _set_naming(root: Path, values: dict[tuple[str, str], Any]) -> None:
    """복사한 naming.yaml의 명명 규칙 칸에 값을 넣는다 (없는 키는 새로 만든다)."""
    path = root / "common/naming.yaml"
    data = read_yaml(path)
    for (section, key), value in values.items():
        data[section][key] = value
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ── 이름 규칙 ─────────────────────────────────────────────────────────


def test_naming_rules_come_from_naming_yaml() -> None:
    physical = read_yaml(DEFAULT_PACK_ROOT / "common/naming.yaml")["physical_name"]
    rules = load_naming_rules()
    assert (rules.max_bytes, rules.separator) == (physical["max_bytes"], physical["word_separator"])
    # 새 키는 R2 후속 PR이 채운다. 그 전(키 없음)이든 뒤든 파일 값을 그대로 읽는다.
    naming = read_yaml(DEFAULT_PACK_ROOT / "common/naming.yaml")
    assert rules.self_reference_prefix == naming["column"].get("self_reference_prefix")
    assert rules.junction_name == naming["table"].get("junction_name")


def test_reserved_words_follow_postgresql_keyword_table() -> None:
    """naming.yaml 주석의 예(END)와, 이름으로 쓸 수 없는 두 분류만 담는지 본다 (D10 임시)."""
    words = load_naming_rules().reserved_words
    assert {"end", "order", "user", "left"} <= words  # left는 TYPE_FUNC_NAME 분류
    assert "name" not in words  # 비예약어는 이름으로 쓸 수 있다


def test_unknown_reserved_word_source_or_postgres_version_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="알 수 없는 예약어 출처"):
        reserved_words("postgresql_99_sql_key_words")
    monkeypatch.setattr(naming, "get_postgresql_version", lambda: (17, 0))
    with pytest.raises(ValueError, match="PostgreSQL 18"):
        reserved_words("postgresql_18_sql_key_words")


def test_agreed_naming_values_are_read(tmp_path: Path) -> None:
    """#11에서 맞춘 값 이름 5개와 새 키 2개를 모두 알아듣는다."""
    root = _copy_pack(tmp_path, "inventory")
    _set_naming(root, AGREED_NAMING)
    rules = load_naming_rules(root)
    assert (rules.self_reference_prefix, rules.junction_name) == ("상위", "parent_child")


@pytest.mark.parametrize(("section", "key"), list(AGREED_NAMING))
def test_each_agreed_value_alone_is_read(tmp_path: Path, section: str, key: str) -> None:
    """칸 하나만 채우고 나머지는 빈칸(미정)이어도 읽는다 (팩 상태 draft)."""
    root = _copy_pack(tmp_path, "inventory")
    _set_naming(root, {**UNSET_NAMING, (section, key): AGREED_NAMING[section, key]})
    rules = load_naming_rules(root)
    assert rules.self_reference_prefix == (
        "상위" if (section, key) == ("column", "self_reference_prefix") else None
    )
    assert rules.junction_name == (
        "parent_child" if (section, key) == ("table", "junction_name") else None
    )


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("table", "prefix", "TB_"),
        ("table", "form", "plural"),
        ("table", "junction_name", "child_parent"),
        ("column", "primary_key", "id"),
        ("column", "foreign_key", "x"),
        ("term", "max_words", 5),
        ("term", "max_words", "None"),  # 글자 None은 null(미정)이 아니다
    ],
)
def test_unknown_naming_value_stops_instead_of_being_ignored(
    tmp_path: Path, section: str, key: str, value: str | int
) -> None:
    root = _copy_pack(tmp_path, "inventory")
    _set_naming(root, {**UNSET_NAMING, (section, key): value})
    assert read_yaml(root / "common/naming.yaml")[section][key] == value
    with pytest.raises(ValueError, match=f"모르는 값이 있음: .*{section}.{key}"):
        load_naming_rules(root)


@pytest.mark.parametrize("value", [5, ["상위"]])
def test_self_reference_prefix_must_be_a_word(tmp_path: Path, value: object) -> None:
    root = _copy_pack(tmp_path, "inventory")
    _set_naming(root, {("column", "self_reference_prefix"): value})
    with pytest.raises(ValueError, match="사전 단어여야 함"):
        load_naming_rules(root)


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("table", "prefix"),
        ("table", "form"),
        ("column", "primary_key"),
        ("column", "foreign_key"),
        ("term", "max_words"),
    ],
)
def test_missing_existing_naming_key_stops(tmp_path: Path, section: str, key: str) -> None:
    """기존 키를 잘못 지우면 미정으로 넘기지 않고 멈춘다 (미정이면 null로 적는다)."""
    root = _copy_pack(tmp_path, "inventory")
    path = root / "common/naming.yaml"
    data = read_yaml(path)
    del data[section][key]
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match=f"{section}.{key} 키가 없음"):
        load_naming_rules(root)


@pytest.mark.parametrize("section", ["table", "column", "term"])
def test_missing_naming_section_stops(tmp_path: Path, section: str) -> None:
    root = _copy_pack(tmp_path, "inventory")
    path = root / "common/naming.yaml"
    data = read_yaml(path)
    del data[section]
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="키가 없음"):
        load_naming_rules(root)


def test_new_naming_keys_may_be_missing(tmp_path: Path) -> None:
    """새 키 두 개는 팩 파일에 들어오기 전(common 0.1.1)에도 읽을 수 있게 없어도 미정이다."""
    root = _copy_pack(tmp_path, "inventory")
    path = root / "common/naming.yaml"
    data = read_yaml(path)
    data["table"].pop("junction_name", None)
    data["column"].pop("self_reference_prefix", None)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rules = load_naming_rules(root)
    assert (rules.self_reference_prefix, rules.junction_name) == (None, None)


@pytest.mark.parametrize("value", [None, ""])
def test_empty_naming_value_is_unset(tmp_path: Path, value: str | None) -> None:
    """null과 빈 문자열은 미정이다. 새 키도 마찬가지다.

    빈 문자열은 #11에서 새로 정한 것이 아니라 이전 load_naming_rules 동작을 그대로 둔 것이다.
    """
    root = _copy_pack(tmp_path, "inventory")
    _set_naming(root, {k: value for k in AGREED_NAMING})
    rules = load_naming_rules(root)
    assert (rules.self_reference_prefix, rules.junction_name) == (None, None)


# ── 사전 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
def test_pack_terms_give_physical_name_domain_and_time_precision(pack: str) -> None:
    lexicon = load_pack_lexicon(pack)
    profile = read_yaml(DEFAULT_PACK_ROOT / "common/naming.yaml")["type_profile"]
    domains = {
        d["name"]: d for d in read_yaml(DEFAULT_PACK_ROOT / "common/domains.yaml")["domains"]
    }
    terms = read_yaml(DEFAULT_PACK_ROOT / pack / "terms.yaml")["terms"]
    for t in terms:
        info = lexicon.term(t["term"])
        assert info is not None
        assert (info.physical_name, info.domain) == (t["physical_name"], t["domain"])
        setting = domains[t["domain"]]["postgres"][profile]
        if setting["type"] in ("time", "timestamp", "timestamptz"):
            assert info.time_precision == setting.get("precision")
        else:
            assert info.time_precision is None


def test_timestamp_term_keeps_precision_zero() -> None:
    """#12 댓글 2: 연월일시분초D는 timestamp(0)이고 정리 결과에 정밀도를 남겨야 한다."""
    info = load_pack_lexicon("inventory").term("거래일시")
    assert info is not None and (info.domain, info.time_precision) == ("연월일시분초D", 0)


def test_compose_uses_standard_words_and_pack_terms() -> None:
    lexicon = load_pack_lexicon("inventory")
    assert physical_name("설비코드", lexicon) == "eqpm_cd"  # 공통 단어 설비 + 코드
    assert physical_name("상위 설비코드", lexicon) == "up_eqpm_cd"  # 공백은 단어 경계


def test_decomposed_hangul_name_finds_the_same_term_and_name() -> None:
    """한글을 자모로 나눠 저장한 이름(NFD)도 같은 용어·물리명을 찾는다 (A03 ID와 같은 NFC 기준)."""
    lexicon = load_pack_lexicon("inventory")
    decomposed = unicodedata.normalize("NFD", "창고코드")
    assert decomposed != "창고코드"
    assert lexicon.term(decomposed) == lexicon.term("창고코드")
    assert physical_name(decomposed, lexicon) == physical_name("창고코드", lexicon) == "wrhus_cd"
    spaced = unicodedata.normalize("NFD", "창고 명")  # 띄어 쓴 이름도 조각마다 같은 기준
    assert physical_name(spaced, lexicon) == "wrhus_nm"


def _add_pack_word(root: Path, word: str, abbreviation: str) -> None:
    path = root / "inventory" / "words.yaml"
    data = read_yaml(path)
    common = read_yaml(root / "common" / "words.yaml")["words"][0]
    data["words"] = [
        *(data.get("words") or []),
        {**common, "word": word, "abbreviation": abbreviation},
    ]
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_same_name_after_nfc_with_different_content_stops(tmp_path: Path) -> None:
    """한 사전 파일 안에서 NFC로 같아지는 두 항목의 약어가 다르면 어느 쪽도 고르지 않고 멈춘다."""
    root = _copy_pack(tmp_path, "inventory")
    _add_pack_word(root, "보관함", "BOX")
    _add_pack_word(root, unicodedata.normalize("NFD", "보관함"), "WRONG")
    with pytest.raises(ValueError, match=re.escape("inventory/words.yaml: 같은 이름 보관함")):
        load_pack_lexicon("inventory", root)


@pytest.mark.parametrize(
    "change", [{"physical_name": "WRONG_CD"}, {"domain": "명V200"}], ids=["physical_name", "domain"]
)
def test_same_term_after_nfc_with_different_name_or_domain_stops(
    tmp_path: Path, change: dict[str, str]
) -> None:
    """팩 용어도 NFC로 같아지는 두 항목의 물리명이나 도메인이 다르면 멈춘다."""
    root = _copy_pack(tmp_path, "inventory")
    path = root / "inventory" / "terms.yaml"
    data = read_yaml(path)
    (original,) = [t for t in data["terms"] if t["term"] == "창고코드"]
    decomposed = {**original, "term": unicodedata.normalize("NFD", "창고코드"), **change}
    data["terms"] = [*data["terms"], decomposed]
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape("inventory/terms.yaml: 같은 이름 창고코드")):
        load_pack_lexicon("inventory", root)


def test_same_name_after_nfc_with_same_content_is_one_entry(tmp_path: Path) -> None:
    root = _copy_pack(tmp_path, "inventory")
    _add_pack_word(root, "보관함", "BOX")
    _add_pack_word(root, unicodedata.normalize("NFD", "보관함"), "BOX")
    assert physical_name("보관함", load_pack_lexicon("inventory", root)) == "box"


def test_pack_word_still_overrides_common_word_of_the_same_name(tmp_path: Path) -> None:
    """파일 사이의 우선순위(공통 단어 → 팩 단어)는 그대로다. 충돌로 보지 않는다."""
    root = _copy_pack(tmp_path, "inventory")
    common_word = read_yaml(root / "common" / "words.yaml")["words"][0]["word"]
    _add_pack_word(root, common_word, "PACKONLY")
    assert physical_name(common_word, load_pack_lexicon("inventory", root)) == "packonly"


def test_unregistered_word_gives_no_name_instead_of_invented_abbreviation() -> None:
    """D5: `수불`은 공통표준 단어가 없다(inventory words.yaml 주석). 약어를 지어내지 않는다."""
    assert physical_name("수불문서", load_pack_lexicon("inventory")) is None


def test_segmentation_prefers_fewest_pieces_then_longer_first_piece() -> None:
    def lexicon(tokens: dict[str, str]) -> PackLexicon:
        return PackLexicon(terms={}, tokens=tokens, separator="_", digest="t")

    # 앞에서 가장 긴 조각(가나)을 잡으면 막히는 경우에도 다른 분할(가 + 나다)을 찾는다
    assert lexicon({"가나": "X", "가": "A", "나다": "Y"}).compose("가나다") == "A_Y"
    # 조각 수가 같으면 앞 조각이 긴 쪽 (가나 + 다)
    tokens = {"가": "A", "나": "B", "다": "D", "가나": "AB", "나다": "BD"}
    assert lexicon(tokens).compose("가나다") == "AB_D"
    # 조각 수가 적은 쪽 (가나다 하나)
    assert lexicon({**tokens, "가나다": "ABD"}).compose("가나다") == "ABD"
    assert lexicon(tokens).compose("가라") is None


def test_lexicon_digest_follows_file_content_not_version(tmp_path: Path) -> None:
    """D9 판단 자료: 팩 버전 문자열이 같아도 사전 내용이 바뀌면 다른 값이 된다."""
    root = _copy_pack(tmp_path, "inventory")
    same = load_pack_lexicon("inventory", root)
    assert same.digest == load_pack_lexicon("inventory").digest
    terms = root / "inventory/terms.yaml"
    terms.write_text(
        terms.read_text(encoding="utf-8").replace("WRHUS_CD", "WH_CD", 1), encoding="utf-8"
    )
    changed = load_pack_lexicon("inventory", root)
    assert changed.digest != same.digest
    assert physical_name("창고코드", changed) == "wh_cd"


# ── 두 팩 실행 (TC-N06) ──────────────────────────────────────────────


def _req(req_id: str) -> Requirement:
    return Requirement(
        id=req_id,
        source_ref={"file_format": "csv", "row": 2},
        text=f"{req_id} 문장",
        draft_text=f"{req_id} 문장",
        type="FR",
        analysis_version=1,
    )


def _entity(pack: str, entity_id: str, name: str, *attrs: dict[str, Any]) -> Entity:
    return Entity.model_validate(
        {
            "id": entity_id,
            "pack": pack,
            "name": name,
            "description": f"{name} 정보",
            "attributes": [{"req_ids": ["REQ-01"], **a} for a in attrs],
            "req_ids": ["REQ-01"],
        }
    )


def _rel(rel_id: str, parent: str, child: str, **kw: Any) -> Relationship:
    return Relationship.model_validate(
        {
            "id": rel_id,
            "parent": parent,
            "child": child,
            "cardinality": "1:N",
            "optional": False,
            "rationale": '"REQ-01 문장" 근거',
            "req_ids": ["REQ-01"],
            **kw,
        }
    )


def _pack(pack: str) -> PackRef:
    return PackRef(pack, read_yaml(DEFAULT_PACK_ROOT / pack / "manifest.yaml")["version"])


MNT_002 = DesignState(  # maintenance A04 MNT-002: 설비 → 상위 설비 (선택 자기참조)
    run_id="run-mnt",
    requirements=[_req("REQ-01")],
    entities=[
        _entity(
            "maintenance",
            "ENT-eq",
            "설비",
            {
                "id": "ATTR-eq-cd",
                "name": "설비코드",
                "data_type": "varchar",
                "length": 10,
                "is_key": True,
                "nullable": False,
            },
            {
                "id": "ATTR-eq-nm",
                "name": "설비명",
                "data_type": "varchar",
                "length": 200,
                "nullable": False,
            },
        )
    ],
    relationships=[_rel("REL-01", "ENT-eq", "ENT-eq", optional=True)],
)


def test_maintenance_self_reference_reads_prefix_from_naming_yaml(tmp_path: Path) -> None:
    """접두어를 코드로 넘기지 않고 naming.yaml column.self_reference_prefix(상위 → UP)로 읽는다."""
    root = _copy_pack(tmp_path, "maintenance")
    _set_naming(root, {("column", "self_reference_prefix"): "상위"})
    lexicon = load_pack_lexicon("maintenance", root)
    rules = load_naming_rules(root)
    result = normalize(MNT_002, pack=_pack("maintenance"), lexicon=lexicon, rules=rules)
    assert isinstance(result, Normalized), result
    (table,) = result.model.tables
    assert table.physical_name == "eqpm"
    assert [c.physical_name for c in table.columns] == ["eqpm_cd", "eqpm_nm", "up_eqpm_cd"]
    assert result.model.pack_version == _pack("maintenance").version
    assert result.model.lexicon_digest == lexicon.digest


def test_agreed_naming_values_do_not_change_names(tmp_path: Path) -> None:
    """#11 값은 모두 미정일 때의 D4 제안 동작과 같은 뜻이라, 채워도 이름이 바뀌지 않는다.

    자기참조 접두어만 새로 생겨 막혀 있던 자기참조가 풀린다.
    """
    unset = _copy_pack(tmp_path / "unset", "maintenance")
    _set_naming(unset, {**UNSET_NAMING, ("column", "self_reference_prefix"): "상위"})
    agreed = _copy_pack(tmp_path / "agreed", "maintenance")
    _set_naming(agreed, AGREED_NAMING)
    results = [
        normalize(
            MNT_002,
            pack=_pack("maintenance"),
            lexicon=load_pack_lexicon("maintenance", root),
            rules=load_naming_rules(root),
        )
        for root in (unset, agreed)
    ]
    assert all(isinstance(r, Normalized) for r in results), results
    tables = [r.model.tables for r in results if isinstance(r, Normalized)]
    assert tables[0] == tables[1]


def test_maintenance_self_reference_is_blocked_when_prefix_is_unset(tmp_path: Path) -> None:
    """column.self_reference_prefix가 빈칸(미정)이면 막힌다. 실제 팩 값과 상관없이 빈칸으로 본다."""
    root = _copy_pack(tmp_path, "maintenance")
    _set_naming(root, {("column", "self_reference_prefix"): None})
    result = normalize(
        MNT_002,
        pack=_pack("maintenance"),
        lexicon=load_pack_lexicon("maintenance", root),
        rules=load_naming_rules(root),
    )
    assert isinstance(result, NormalizeFailed)
    assert [(p.code, p.decision) for p in result.problems] == [
        (ProblemCode.NAMING_RULE_MISSING, "D4")
    ]


def test_very_long_name_is_reported_as_too_long_instead_of_crashing() -> None:
    """실제 inventory 사전과 정상 PK에서 엔티티 이름이 아주 길어도 멈추지 않고 정리 실패로 돌려준다.

    #129 리뷰: 이전 분할 방식은 "명" * 1000에서 RecursionError로 끝났다.
    """
    design = DesignState(
        run_id="run-long",
        requirements=[_req("REQ-01")],
        entities=[
            _entity(
                "inventory",
                "ENT-long",
                "명" * 1000,
                {
                    "id": "ATTR-wh-cd",
                    "name": "창고코드",
                    "data_type": "varchar",
                    "length": 10,
                    "is_key": True,
                    "nullable": False,
                },
            )
        ],
    )
    result = normalize(
        design,
        pack=_pack("inventory"),
        lexicon=load_pack_lexicon("inventory"),
        rules=load_naming_rules(),
    )
    assert isinstance(result, NormalizeFailed)
    assert [p.code for p in result.problems] == [ProblemCode.NAME_TOO_LONG]


def _long_name_result(entity_name: str, column_name: str = "창고코드") -> Any:
    design = DesignState(
        run_id="run-long",
        requirements=[_req("REQ-01")],
        entities=[
            _entity(
                "inventory",
                "ENT-long",
                entity_name,
                {
                    "id": "ATTR-key",
                    "name": column_name,
                    "data_type": "varchar",
                    "length": 10,
                    "is_key": True,
                    "nullable": False,
                },
            )
        ],
    )
    return normalize(
        design,
        pack=_pack("inventory"),
        lexicon=load_pack_lexicon("inventory"),
        rules=load_naming_rules(),
    )


def test_very_long_column_name_is_reported_as_too_long() -> None:
    result = _long_name_result("창고", column_name="명" * 1000)
    assert isinstance(result, NormalizeFailed)
    assert [p.code for p in result.problems] == [ProblemCode.NAME_TOO_LONG]


@pytest.mark.parametrize("name", ["X" + "명" * 1000, "명" * 1000 + "X"])
def test_very_long_name_with_unregistered_letter_is_unresolved(name: str) -> None:
    """사전에 없는 글자가 앞이나 뒤에 섞인 긴 이름은 물리명을 만들 수 없다고 알린다."""
    result = _long_name_result(name)
    assert isinstance(result, NormalizeFailed)
    assert [p.code for p in result.problems] == [ProblemCode.UNRESOLVED_NAME]


def test_inventory_inv005_reports_unregistered_words_as_pending_only() -> None:
    """inventory A04 INV-005: 수불문서 → 수불내역(식별), 품목 → 수불내역.

    `수불`·`순번`이 공통표준 단어에 없어 이름을 못 만든다. 이름 문제만 D5 대기로 남고, 빈 이름
    때문에 엉뚱한 FK 충돌이 생기지 않아야 한다.
    """
    varchar = {"data_type": "varchar", "length": 10, "is_key": True, "nullable": False}
    design = DesignState(
        run_id="run-inv",
        requirements=[_req("REQ-01")],
        entities=[
            _entity(
                "inventory",
                "ENT-doc",
                "수불문서",
                {"id": "ATTR-doc-no", "name": "수불문서번호", **varchar},
            ),
            _entity(
                "inventory",
                "ENT-line",
                "수불내역",
                {
                    "id": "ATTR-line-sn",
                    "name": "내역순번",
                    "data_type": "integer",
                    "is_key": True,
                    "nullable": False,
                },
                {
                    "id": "ATTR-line-qty",
                    "name": "거래수량",
                    "data_type": "numeric",
                    "precision": 10,
                    "scale": 3,
                    "nullable": False,
                },
            ),
            _entity(
                "inventory",
                "ENT-item",
                "품목",
                {"id": "ATTR-item-cd", "name": "품목코드", **varchar},
            ),
        ],
        relationships=[
            _rel("REL-01", "ENT-doc", "ENT-line", identifying=True),
            _rel("REL-02", "ENT-item", "ENT-line"),
        ],
    )
    result = normalize(
        design,
        pack=_pack("inventory"),
        lexicon=load_pack_lexicon("inventory"),
        rules=load_naming_rules(),
    )
    assert isinstance(result, NormalizeFailed)
    assert {(p.code, p.decision, p.pending) for p in result.problems} == {
        (ProblemCode.UNRESOLVED_NAME, "D5", True)
    }
    assert sorted(p.detail.split(":")[0] for p in result.problems) == [
        "내역순번",
        "수불내역",
        "수불문서",
        "수불문서번호",
    ]
