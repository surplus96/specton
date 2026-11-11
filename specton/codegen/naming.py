"""물리명 만들기와 이름 검사 (#12).

물리명은 팩 용어의 `physical_name`을 먼저 쓴다. 없으면 사전 단어(공통표준 단어, 팩 단어,
팩 용어)로 논리명을 끝까지 나눠 약어를 잇는다. 나눌 수 없으면 약어를 지어내지 않고
"이름 없음"으로 돌려준다 (D5 결정 대기). 값은 모두 `domain_packs/`에서 읽고 코드에 적지 않는다.

이 모듈은 LLM client를 import하지 않는다.
"""

import hashlib
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pglast import keywords as pg_keywords
from pglast.parser import get_postgresql_version

from specton.codegen.model import Problem, ProblemCode, problem
from specton.contracts.base import SqlType
from specton.packs.build import read_yaml

DEFAULT_PACK_ROOT = Path(__file__).resolve().parents[2] / "domain_packs"
_TIME_TYPES = frozenset({SqlType.TIME, SqlType.TIMESTAMP, SqlType.TIMESTAMPTZ})
# naming.yaml `reserved_words_source`가 가리키는 목록. 목록 파일은 아직 없어(D10, #11) PostgreSQL
# 파서와 같은 키워드 표를 쓰는 pglast에서 읽는다. 표에서 이름으로 못 쓰는 두 분류만 거부한다.
_RESERVED_SOURCES = {"postgresql_18_sql_key_words": 18}
# naming.yaml 명명 규칙 칸마다 알아듣는 값 이름. null(빈칸)은 「미정」이고, 값 이름은 「정했음」이다
# (#11 R4 초안·R2 답). 미정이면 D4 제안 동작을 쓴다: 접두어 없음, 사전 약어 그대로(단수·복수 변환
# 없음), PK는 용어 물리명, FK는 부모 키 물리명, 연결 테이블은 부모+자식, 단어 수 제한 없음.
# 지금 아는 값은 모두 이 D4 제안 동작과 같은 뜻이라, 값이 들어와도 결과 이름은 바뀌지 않는다.
# 임시(#11): 값 이름은 공통 팩이 draft이고 팩 형식(ADR-0009)이 제안 상태라 바뀔 수 있음.
#   같은 허용 값 목록이 팩 로더 모델(specton/packs/loader.py `_TermRule`·`_TableRule`·
#   `_ColumnRule`, 파일 모양 검사)에도 있다. 값 이름을 바꾸면 두 곳을 함께 고친다.
_KNOWN_NAMING_VALUES: dict[tuple[str, str], frozenset[str]] = {
    ("physical_name", "unresolved"): frozenset({"error", "technical_id"}),
    ("table", "prefix"): frozenset({"none"}),  # 테이블 접두어 없음
    ("table", "form"): frozenset({"as_dictionary"}),  # 사전 약어 그대로, 단수·복수 변환 없음
    ("table", "junction_name"): frozenset({"parent_child"}),  # 부모 물리명 + 자식 물리명
    ("column", "primary_key"): frozenset({"term_physical_name"}),  # 용어 물리명 그대로
    ("column", "foreign_key"): frozenset({"parent_key_physical_name"}),  # 부모 키 물리명 그대로
    ("column", "repeated_foreign_key"): frozenset({"manual", "relationship_id"}),
    ("term", "max_words"): frozenset({"unlimited"}),  # 용어당 단어 수 제한 없음
    ("term", "word_aliases"): frozenset({"disabled", "official_unambiguous"}),
}
# #11에서 새로 더한 키. 팩 파일에 아직 없을 수 있어 키가 없어도 미정으로 본다 (_naming_value).
_NEW_NAMING_KEYS = frozenset(
    {
        ("physical_name", "unresolved"),
        ("table", "junction_name"),
        ("column", "self_reference_prefix"),
        ("column", "repeated_foreign_key"),
        ("term", "word_aliases"),
    }
)


@dataclass(frozen=True)
class TermInfo:
    """팩 용어에서 얻는 값 (#91: 속성 이름이 용어명과 같으면 그 용어로 본다)."""

    physical_name: str
    domain: str
    time_precision: int | None = None
    data_type: SqlType | None = None  # 도메인 타입 (naming.yaml type_profile 기준)


class Lexicon(Protocol):
    """팩 용어·단어 사전 조회."""

    @property
    def digest(self) -> str:
        """사전을 만든 팩 파일 내용의 해시. 결과 모델에 남긴다."""
        ...

    def term(self, logical_name: str) -> TermInfo | None:
        """논리명과 이름이 같은 팩 용어. 없으면 None."""
        ...

    def compose(self, logical_name: str) -> str | None:
        """사전 단어 약어를 이어 만든 물리명. 만들 수 없으면 None."""
        ...


@dataclass(frozen=True)
class NamingRules:
    """이름 규칙. 값은 `domain_packs/common/naming.yaml`에서 읽어 넘긴다 (코드에 적지 않음).

    `self_reference_prefix`는 자기참조 FK 칸 앞에 붙일 사전 단어다 (naming.yaml
    `column.self_reference_prefix`, 예: `상위` → 약어 `UP`). 값이 없으면(미정) 자기참조 관계는
    `naming_rule_missing` 문제로 막는다.
    `junction_name`은 N:M 연결 테이블 이름 규칙이다 (naming.yaml `table.junction_name`).
    `parent_child`와 미정(None)은 같은 동작이다: 부모 테이블 물리명 + 자식 테이블 물리명 (D4).
    """

    max_bytes: int
    reserved_words: frozenset[str]  # 소문자
    unresolved: str = "error"
    separator: str = "_"
    self_reference_prefix: str | None = None
    junction_name: str | None = None
    repeated_foreign_key: str | None = None  # 누락/None/manual은 기존 D4 사람 조치


def physical_name(logical_name: str, lexicon: Lexicon) -> str | None:
    """팩 용어 → 사전 조합 순으로 물리명을 찾는다.

    DDL에 쓰므로 소문자로 바꾼다 (naming.yaml `ddl_case`).
    """
    term = lexicon.term(logical_name)
    name = term.physical_name if term else lexicon.compose(logical_name)
    return name.lower() if name else None


def check_name(name: str, target: str, rules: NamingRules) -> Iterator[Problem]:
    """한 이름의 길이·예약어 검사. 중복은 모아서 따로 본다."""
    size = len(name.encode("utf-8"))
    if size > rules.max_bytes:
        yield problem(
            ProblemCode.NAME_TOO_LONG, target, f"{name}: {size}바이트 > {rules.max_bytes}"
        )
    if name.lower() in rules.reserved_words:
        yield problem(ProblemCode.RESERVED_WORD, target, f"{name}: 예약어")


def unresolved(logical_name: str, target: str) -> Problem:
    return problem(
        ProblemCode.UNRESOLVED_NAME,
        target,
        f"{logical_name}: 팩 용어·사전으로 물리명을 만들 수 없음",
        decision="D5",
        pending=True,
    )


# ── 팩 연결 ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PackLexicon:
    """팩 파일에서 읽은 사전. `load_pack_lexicon`으로 만든다."""

    terms: Mapping[str, TermInfo]
    tokens: Mapping[str, str]  # 논리명 조각 → 약어 (공통표준 단어, 팩 단어, 팩 용어)
    separator: str
    digest: str

    def term(self, logical_name: str) -> TermInfo | None:
        return self.terms.get(_nfc(logical_name))

    def compose(self, logical_name: str) -> str | None:
        """공백으로 나눈 뒤 각 조각을 사전 항목으로 끝까지 나눈다. 하나라도 못 나누면 None."""
        parts: list[str] = []
        for chunk in _nfc(logical_name).split():
            split = _segment(chunk, self.tokens)
            if split is None:
                return None
            parts.extend(self.tokens[t] for t in split)
        return self.separator.join(parts) if parts else None


def _nfc(name: str) -> str:
    """한글 조합 방식 차이(NFC·NFD)를 맞춘다. ID 계산(`specton.ids.stable_id`)과 같은 기준이다."""
    return unicodedata.normalize("NFC", name)


def _by_nfc_name[V](pairs: Iterable[tuple[str, V]], where: str) -> dict[str, V]:
    """한 사전 파일의 항목을 NFC 이름으로 모은다.

    NFC로 바꾸면 같은 이름인데 내용(물리명·도메인 등)이 다르면 순서에 따라 조용히 덮어쓰지 않고
    멈춘다. 내용까지 같으면 하나로 본다.
    """
    found: dict[str, V] = {}
    for name, value in pairs:
        key = _nfc(name)
        if key in found and found[key] != value:
            raise ValueError(f"{where}: 같은 이름 {key}에 내용이 다른 항목이 둘 이상 있습니다")
        found[key] = value
    return found


def _segment(text: str, tokens: Mapping[str, str]) -> tuple[str, ...] | None:
    """`text`를 사전 항목으로 빈틈없이 나눈다. 항목 수가 가장 적은 분할을 고른다.

    같은 수면 앞 조각이 긴 쪽을 고른다. 같은 입력이면 항상 같은 분할이다.
    뒤에서부터 채우는 반복문이라 이름이 길어도 재귀 깊이 한도에 걸리지 않는다. 위치마다
    최소 조각 수와 다음 조각의 끝 위치만 두고 마지막에 한 번 조립해, 메모리는 이름 길이에 비례한다.
    """
    size = len(text)
    longest = max((len(t) for t in tokens), default=0)
    pieces: list[int | None] = [None] * (size + 1)  # 그 위치부터 끝까지의 최소 조각 수
    next_end: list[int] = [0] * (size + 1)  # 그 위치에서 고른 첫 조각의 끝 위치
    pieces[size] = 0
    for start in range(size - 1, -1, -1):
        for end in range(min(size, start + longest), start, -1):  # 긴 조각부터
            rest = pieces[end]
            if rest is None or text[start:end] not in tokens:
                continue
            current = pieces[start]
            if current is None or rest + 1 < current:  # 같은 수면 먼저 본 긴 조각을 둔다
                pieces[start] = rest + 1
                next_end[start] = end
    if pieces[0] is None:
        return None
    result: list[str] = []
    position = 0
    while position < size:
        result.append(text[position : next_end[position]])
        position = next_end[position]
    return tuple(result)


def load_naming_rules(root: Path = DEFAULT_PACK_ROOT) -> NamingRules:
    """`common/naming.yaml`에서 이름 규칙을 읽는다.

    명명 규칙 칸(테이블 접두어·단복수·연결 테이블 이름, PK·FK 칸 이름, 용어당 최대 단어 수)은
    빈칸(미정)이거나 알아듣는 값 이름(`_KNOWN_NAMING_VALUES`)이어야 한다. 모르는 값은 조용히
    무시하지 않고 멈춘다. 기존 키가 없어도 멈추고, 새 키 두 개만 없어도 된다(`_naming_value`).
    값 이름 목록의 기준은 팩 로더 모델(specton/packs/loader.py
    `_TermRule`·`_TableRule`·`_ColumnRule`)이다.
    `column.self_reference_prefix`는 사전 단어(예: `상위`)를 읽는다. 팩 로더(`_Strict`의
    `str_strip_whitespace`)처럼 앞뒤 공백을 지우고, 공백만 있으면 미정이다. 사전에 없는 단어면
    모델 정리가 이름 없음(D5) 문제로 돌려준다. 값 이름 칸은 로더도 공백 붙은 값을 거절하므로
    공백을 지우지 않는다.
    """
    naming = read_yaml(root / "common" / "naming.yaml")
    physical = naming["physical_name"]
    if physical["ddl_case"] != "lower":
        raise ValueError(f"지원하지 않는 ddl_case: {physical['ddl_case']}")
    unknown = {
        f"{section}.{key}": value
        for (section, key), known in _KNOWN_NAMING_VALUES.items()
        if (value := _naming_value(naming, section, key)) is not None
        and not (isinstance(value, str) and value in known)
    }
    if unknown:
        allowed = {f"{s}.{k}": sorted(v) for (s, k), v in _KNOWN_NAMING_VALUES.items()}
        raise ValueError(
            f"naming.yaml 명명 규칙에 모르는 값이 있음: {unknown} (빈칸 또는 다음 값만: {allowed})"
        )
    if physical.get("unresolved", "error") not in {"error", "technical_id"}:
        raise ValueError("physical_name.unresolved는 error 또는 technical_id여야 합니다")
    prefix = _naming_value(naming, "column", "self_reference_prefix")
    if prefix is not None and not isinstance(prefix, str):
        raise ValueError(f"naming.yaml column.self_reference_prefix는 사전 단어여야 함: {prefix!r}")
    if prefix is not None:
        prefix = prefix.strip() or None
    return NamingRules(
        max_bytes=physical["max_bytes"],
        unresolved=physical.get("unresolved", "error"),
        reserved_words=reserved_words(naming["reserved_words_source"]),
        separator=physical["word_separator"],
        self_reference_prefix=prefix,
        junction_name=_naming_value(naming, "table", "junction_name"),  # 위에서 값 이름 확인됨
        repeated_foreign_key=_naming_value(naming, "column", "repeated_foreign_key"),
    )


def _naming_value(naming: Mapping[str, Any], section: str, key: str) -> Any:
    """명명 규칙 칸의 값. 빈칸이면 미정(None)이다.

    - `null`: 미정 (#11 합의, #132 로더와 같은 뜻).
    - 빈 문자열: 미정. #11에서 새로 정한 것이 아니라, 이전 `load_naming_rules`가 빈 문자열을
      빈칸으로 보던 동작을 그대로 둔 것이다.
    - 키가 없음: 새 키(`_NEW_NAMING_KEYS`)만 미정으로 본다. 새 키가 팩 파일에 들어오기 전
      (common 0.1.1)에도 읽을 수 있게 하기 위해서다. 기존 키나 묶음이 없으면 잘못 지운 것일 수
      있어 기본 동작으로 넘기지 않고 멈춘다. 이 경로(normalize_step 등)는 팩 로더를 거치지
      않아서 여기서 직접 확인한다.
    """
    block = naming.get(section)
    if not isinstance(block, Mapping) or key not in block:
        if (section, key) in _NEW_NAMING_KEYS:
            return None
        raise ValueError(f"naming.yaml에 {section}.{key} 키가 없음 (미정이면 null로 적는다)")
    value = block[key]
    return None if value in (None, "") else value


def reserved_words(source: str) -> frozenset[str]:
    """예약어 목록. 이름으로 쓸 수 없는 키워드(RESERVED, TYPE_FUNC_NAME)만 담는다."""
    major = _RESERVED_SOURCES.get(source)
    if major is None:
        raise ValueError(f"알 수 없는 예약어 출처: {source}")
    installed = get_postgresql_version()[0]
    if installed != major:
        raise ValueError(f"예약어 출처는 PostgreSQL {major}인데 pglast는 {installed} 기준")
    return frozenset(pg_keywords.RESERVED_KEYWORDS | pg_keywords.TYPE_FUNC_NAME_KEYWORDS)


def load_pack_lexicon(pack: str, root: Path = DEFAULT_PACK_ROOT) -> PackLexicon:
    """팩 용어(`<pack>/terms.yaml`), 공통·팩 단어, 공통 도메인, 명명 규칙을 읽어 사전을 만든다.

    시각 타입 용어의 소수 초 자릿수는 naming.yaml `type_profile`에 맞는 도메인 설정에서 읽는다.
    """
    from specton.packs.lexicon_sources import validate_lexicon_sources

    validate_lexicon_sources(root / pack)
    files = [
        root / "common" / "naming.yaml",
        root / "common" / "domains.yaml",
        root / "common" / "words.yaml",
        root / pack / "words.yaml",
        root / pack / "terms.yaml",
    ]
    naming, domains_file, common_words, pack_words, terms_file = (read_yaml(f) for f in files)
    profile = naming["type_profile"]
    domains = {d["name"]: d for d in domains_file["domains"]}
    terms = _by_nfc_name(
        ((t["term"], _term_info(t, domains[t["domain"]], profile)) for t in terms_file["terms"]),
        f"{pack}/terms.yaml",
    )
    # 파일 사이에서는 공통 단어 → 팩 단어 → 팩 용어 순서로 뒤의 것이 덮는다 (정한 우선순위)
    tokens: dict[str, str] = {}
    for source, where in ((common_words, "common/words.yaml"), (pack_words, f"{pack}/words.yaml")):
        words = ((w["word"], w["abbreviation"]) for w in source.get("words") or [])
        tokens.update(_by_nfc_name(words, where))
    tokens.update({name: info.physical_name for name, info in terms.items()})
    aliases = _naming_value(naming, "term", "word_aliases")
    if aliases not in (None, "disabled", "official_unambiguous"):
        raise ValueError(f"지원하지 않는 term.word_aliases: {aliases!r}")
    if aliases == "official_unambiguous":
        tokens.update(_official_aliases(common_words.get("words") or [], tokens))
    digest = hashlib.sha256()
    for f in files:
        digest.update(f.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(f.read_bytes() + b"\0")
    return PackLexicon(
        terms=terms,
        tokens=tokens,
        separator=naming["physical_name"]["word_separator"],
        digest=digest.hexdigest(),
    )


def _official_aliases(
    words: Iterable[Mapping[str, Any]], tokens: Mapping[str, str]
) -> dict[str, str]:
    """공식 이음동의어만 사용한다. 기존 이름·금칙어·둘 이상의 표준어로 이어지는 이름은 제외한다.

    원래 논리명은 유지하며 SC-04의 이음동의어 진단도 유지한다. 팩의 자유 동의어를 수집하거나
    전이적으로 치환하지 않으며, 약어는 해당 공식 표준어의 값만 사용한다.
    """
    candidates: dict[str, dict[str, str]] = {}
    forbidden: set[str] = set()
    for word in words:
        forbidden.update(_nfc(s) for s in word.get("forbidden_synonyms") or [])
        for alias in word.get("synonyms") or []:
            candidates.setdefault(_nfc(alias), {})[_nfc(word["word"])] = word["abbreviation"]
    return {
        alias: next(iter(targets.values()))
        for alias, targets in candidates.items()
        if alias
        and alias not in tokens
        and alias not in forbidden
        and len(targets) == 1
        and all(
            tokens.get(name, abbreviation) == abbreviation for name, abbreviation in targets.items()
        )
    }


def _term_info(term: Mapping[str, Any], domain: Mapping[str, Any], profile: str) -> TermInfo:
    setting = domain["postgres"][profile]
    precision = setting.get("precision") if SqlType(setting["type"]) in _TIME_TYPES else None
    return TermInfo(term["physical_name"], term["domain"], precision, SqlType(setting["type"]))
