"""물리명 만들기와 이름 검사 (#12).

물리명은 팩 용어의 `physical_name`을 먼저 쓴다. 없으면 사전 단어(공통표준 단어, 팩 단어,
팩 용어)로 논리명을 끝까지 나눠 약어를 잇는다. 나눌 수 없으면 약어를 지어내지 않고
"이름 없음"으로 돌려준다 (D5 결정 대기). 값은 모두 `domain_packs/`에서 읽고 코드에 적지 않는다.

이 모듈은 LLM client를 import하지 않는다.
"""

import hashlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cache
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

    `self_reference_prefix`는 자기참조 FK 칸 앞에 붙일 사전 단어다. naming.yaml
    `column.foreign_key`가 비어 있어 아직 값이 없다 (D4 제안: `상위`, 팀 확인 후 R2가 팩에 반영).
    값이 없으면 자기참조 관계는 `naming_rule_missing` 문제로 막는다.
    """

    max_bytes: int
    reserved_words: frozenset[str]  # 소문자
    separator: str = "_"
    self_reference_prefix: str | None = None


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
        return self.terms.get(logical_name)

    def compose(self, logical_name: str) -> str | None:
        """공백으로 나눈 뒤 각 조각을 사전 항목으로 끝까지 나눈다. 하나라도 못 나누면 None."""
        parts: list[str] = []
        for chunk in logical_name.split():
            split = _segment(chunk, self.tokens)
            if split is None:
                return None
            parts.extend(self.tokens[t] for t in split)
        return self.separator.join(parts) if parts else None


def _segment(text: str, tokens: Mapping[str, str]) -> tuple[str, ...] | None:
    """`text`를 사전 항목으로 빈틈없이 나눈다. 항목 수가 가장 적은 분할을 고른다.

    같은 수면 앞 조각이 긴 쪽을 고른다. 같은 입력이면 항상 같은 분할이다.
    """

    @cache
    def best(start: int) -> tuple[str, ...] | None:
        if start == len(text):
            return ()
        found: tuple[str, ...] | None = None
        for end in range(len(text), start, -1):  # 긴 조각부터
            piece = text[start:end]
            if piece not in tokens:
                continue
            rest = best(end)
            if rest is not None and (found is None or len(rest) + 1 < len(found)):
                found = (piece, *rest)
        return found

    return best(0)


def load_naming_rules(
    root: Path = DEFAULT_PACK_ROOT, *, self_reference_prefix: str | None = None
) -> NamingRules:
    """`common/naming.yaml`에서 이름 규칙을 읽는다.

    아직 해석하지 않는 규칙(테이블 접두어·복수형, PK·FK 칸 이름, 용어당 최대 단어 수)에
    값이 들어오면 조용히 무시하지 않고 멈춘다. 빈칸일 때의 동작은 D4 제안이다:
    접두어 없음, PK는 용어 물리명 그대로, FK는 부모 키 물리명.
    """
    naming = read_yaml(root / "common" / "naming.yaml")
    physical = naming["physical_name"]
    if physical["ddl_case"] != "lower":
        raise ValueError(f"지원하지 않는 ddl_case: {physical['ddl_case']}")
    filled = {
        f"{section}.{key}": naming[section][key]
        for section, keys in (
            ("table", ("prefix", "form")),
            ("column", ("primary_key", "foreign_key")),
            ("term", ("max_words",)),  # ADR-0009 명명 규칙 빈칸: 용어당 최대 단어 수
        )
        for key in keys
        if naming[section].get(key) not in (None, "")
    }
    if filled:
        raise ValueError(f"naming.yaml 규칙을 아직 해석하지 않음 (#12 D4): {filled}")
    return NamingRules(
        max_bytes=physical["max_bytes"],
        reserved_words=reserved_words(naming["reserved_words_source"]),
        separator=physical["word_separator"],
        self_reference_prefix=self_reference_prefix,
    )


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
    terms = {t["term"]: _term_info(t, domains[t["domain"]], profile) for t in terms_file["terms"]}
    tokens: dict[str, str] = {}
    for source in (common_words.get("words") or [], pack_words.get("words") or []):
        tokens.update({w["word"]: w["abbreviation"] for w in source})
    tokens.update({name: info.physical_name for name, info in terms.items()})
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


def _term_info(term: Mapping[str, Any], domain: Mapping[str, Any], profile: str) -> TermInfo:
    setting = domain["postgres"][profile]
    precision = setting.get("precision") if SqlType(setting["type"]) in _TIME_TYPES else None
    return TermInfo(term["physical_name"], term["domain"], precision, SqlType(setting["type"]))
