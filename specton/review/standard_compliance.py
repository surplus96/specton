"""표준 준수 검사 SC-01~06 (#15). 정리에 성공한 설계의 칸을 공통표준 원본과 비교한다.

처리 기준은 #15 R1 답(11/7·11/9)과 R2 답(11/8·11/9)을 따른다.

- 대상은 **팩 용어가 아닌 속성에서 온 칸**이다(`Column.domain`이 비어 있는 속성 칸).
  팩 용어와 이름이 같은 속성은 A03 출력 검사가 타입·길이까지 거르고, 정리 단계의
  `domain_type_mismatch`는 RULE-03이 지적한다. 같은 대상·원인을 SC에서 다시 내지 않는다.
  관계에서 파생된 FK 칸은 부모 칸을 따른다.
- 비교 기준은 실행 때 읽는 공통표준 원본(`domain_packs/sources/*.csv`)이다. 팩은 바꾸지 않는다.
  원본은 `sources.yaml`의 sha256으로 고정하고, 다르면 결과를 재현할 수 없으므로 실행 오류로 멈춘다.
  폐기된 줄은 빼고, 폐기를 빼고도 같은 이름에 내용이 다른 줄이 있으면 어느 줄로 비교할지 추측하지
  않고 미진단으로 센다.
- 이름은 팩 낱말·공식 단어·공식 금칙어·공식 이음동의어로 끝에서부터 긴 단어를 먼저 맞춰 나눈다
  (`RATIONALE.md`). 끝까지 나눌 수 없으면 팩에도 공식에도 없는
  부분이 있다는 뜻이라 SC-01이다. 팩에 등록한 낱말(공통 팩·도메인 팩 `words.yaml`)은 의도한 선택이라
  지적하지 않으므로(예: 「장부」, 팩 `standard_selection.yaml`) SC-04는 팩에 없는
  금칙어(`forbidden_word`)와 이음동의어(`synonym`, #260)만 지적한다. 정리를 통과한 이름은 모두
  팩 사전으로 풀린 것이라 지금 팩으로는 두 검사가 실제로 0건이다.
- SC-03은 분류어(이름 끝 단어)의 도메인 분류에 속한 공식 도메인들과 칸의 타입이 다를 때,
  SC-06은 공식 용어와 이름이 같고 타입·길이·소수 자릿수가 그 도메인과 다를 때다. 한 칸에서 SC-03이
  나면 SC-06 지적은 내지 않는다(집계에서는 SC-06도 부적합으로 센다).
  타입은 `naming.yaml`의 `type_profile`(strict·pg_native)로 고른다.
  시각 타입의 소수 초 자릿수는 속성 계약에 칸이 없어 설계를 고쳐도 풀리지 않으므로 비교하지 않는다.
- SC-04(금칙어)·SC-05(공식 용어와 약어 불일치)는 이름을 바꿀지 팩을 고칠지 사람이 정한다
  (`requires_manual_review=True`). minor만 있으면 켜지 않는다. SC-04 이음동의어는
  `rules.yaml` `subtypes.synonym`대로 minor 참고다.
- 비교할 기준이 없으면 통과가 아니라 미진단이다. 항목별로 전체·진단·미진단·적합 칸 수와
  준수율(적합 칸 / 진단 칸 * 100, `rules.yaml` `compliance_rate`)을 함께 돌려준다.
- 심각도는 `rules.yaml`에서 읽고, 정하지 않은 값이면 그 지적이 필요해질 때 멈춘다.

그래프 연결(R1, #17)은 이 함수를 불러 `findings`·`requires_manual_review`를 기존 경로로 넘긴다.
이 모듈은 LLM client와 그래프·노드 모듈을 import하지 않는다.
"""

import hashlib
import unicodedata
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from specton.contracts import DesignState, Finding
from specton.contracts.base import SqlType
from specton.contracts.findings import FindingSource, FindingTarget, Severity
from specton.contracts.normalized import Column, NormalizedModel, Table
from specton.packs.build import DEFAULT_ROOT, domain_entry, read_csv, read_yaml, word_entry
from specton.packs.loader import Word, load_common, load_pack
from specton.review.fingerprint import fingerprint
from specton.review.rule_policy import apply_policy, load_policies

CODES = ("SC-01", "SC-02", "SC-03", "SC-04", "SC-05", "SC-06")
Profile = Literal["strict", "pg_native"]
_SOURCES = Path("sources") / "sources.yaml"


# ── 공통표준 원본 ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class OfficialWord:
    abbreviation: str
    is_classifier: bool
    domain_group: str | None
    forbidden: tuple[str, ...]
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class OfficialTerm:
    abbreviation: str
    domain: str


@dataclass(frozen=True)
class DomainSpec:
    """공식 도메인 하나를 타입 프로필 하나로 옮긴 것."""

    domain_class: str
    type: SqlType
    length: int | None
    scale: int | None


@dataclass(frozen=True)
class OfficialStandard:
    """검사에 쓰는 공통표준 원본. 폐기 줄을 뺐고, 내용이 다른 같은 이름은 `ambiguous_*`에만 있다.

    `class_types`는 도메인 분류 → 타입 프로필 → 그 분류에 속한 공식 도메인들의 타입이다.
    이름이 겹치는 도메인(예: 번호C9가 CHAR·VARCHAR 두 줄)도 분류어 타입 비교에는
    두 타입을 모두 넣는다.
    """

    edition: str
    sha256: Mapping[str, str]  # words·terms·domains → 원본 sha256 (CRLF를 LF로 맞춘 값)
    words: Mapping[str, OfficialWord]
    terms: Mapping[str, OfficialTerm]
    domains: Mapping[str, Mapping[Profile, DomainSpec]]  # 도메인 이름 → 프로필 → 명세
    class_types: Mapping[str, Mapping[Profile, frozenset[SqlType]]]
    ambiguous_words: frozenset[str] = frozenset()
    ambiguous_terms: frozenset[str] = frozenset()
    ambiguous_domains: frozenset[str] = frozenset()

    def forbidden_index(self) -> dict[str, str]:
        """금칙어 → 대신 쓸 공식 단어. 한 금칙어가 여러 단어에 걸리면 이름순으로 먼저인 단어."""
        index: dict[str, str] = {}
        for name in sorted(self.words):
            for bad in self.words[name].forbidden:
                index.setdefault(_nfc(bad), name)
        return index

    def synonym_index(self) -> dict[str, str]:
        """이음동의어 → 대신 쓸 공식 단어. 그 자체로 공식 단어이거나 금칙어인 이름은 뺀다.

        공식 단어는 표준어로 써도 되고, 금칙어는 SC-04 금칙어(major)로 이미 지적한다.
        한 이음동의어가 여러 단어에 걸리면 이름순으로 먼저인 단어.
        """
        skip = {*self.words, *self.ambiguous_words, *self.forbidden_index()}
        index: dict[str, str] = {}
        for name in sorted(self.words):
            for alias in self.words[name].synonyms:
                if (alias := _nfc(alias)) not in skip:
                    index.setdefault(alias, name)
        return index


def load_official_standard(
    *, root: Path = DEFAULT_ROOT, profiles: Iterable[Profile] = ("strict", "pg_native")
) -> OfficialStandard:
    """`sources/sources.yaml`이 가리키는 공통표준 CSV를 읽는다. sha256이 다르면 멈춘다."""
    sources = read_yaml(root / _SOURCES)
    digests, rows = _verified_rows(sources, (root / _SOURCES).parent)
    words, ambiguous_words = _unique(
        (
            entry["word"],
            OfficialWord(
                entry["abbreviation"],
                entry["is_classifier"],
                entry["domain_group"],
                tuple(entry["forbidden_synonyms"]),
                tuple(entry["synonyms"]),
            ),
        )
        for entry in map(word_entry, rows["words"])
    )
    terms, ambiguous_terms = _unique(
        (
            r["공통표준용어명"].strip(),
            OfficialTerm(r["공통표준용어영문약어명"].strip(), r["공통표준도메인명"].strip()),
        )
        for r in rows["terms"]
    )
    domains, ambiguous_domains, class_types = _domains(rows["domains"], tuple(profiles))
    return OfficialStandard(
        edition=str(sources["edition"]),
        sha256=digests,
        words=words,
        terms=terms,
        domains=domains,
        class_types=class_types,
        ambiguous_words=ambiguous_words,
        ambiguous_terms=ambiguous_terms,
        ambiguous_domains=ambiguous_domains,
    )


def _verified_rows(
    sources: Mapping[str, Any], folder: Path
) -> tuple[dict[str, str], dict[str, list[dict[str, str]]]]:
    """원본 파일마다 sha256을 확인하고 줄을 읽는다(폐기 줄은 `read_csv`가 뺀다)."""
    digests: dict[str, str] = {}
    rows: dict[str, list[dict[str, str]]] = {}
    for key in ("words", "terms", "domains"):
        spec = sources["files"][key]
        path = folder / spec["path"]
        expected = spec.get("sha256")
        if not expected:
            raise ValueError(
                f"sources.yaml files.{key}.sha256이 없습니다 (표준 준수 검사 원본 고정)"
            )
        actual = _content_sha256(path)
        if actual != expected:
            raise ValueError(
                f"공통표준 원본 {spec['path']}의 sha256이 sources.yaml과 다릅니다: "
                f"{actual} ≠ {expected}"
            )
        digests[key] = actual
        rows[key] = read_csv(path)
    return digests, rows


def _domains(
    rows: Sequence[dict[str, str]], profiles: tuple[Profile, ...]
) -> tuple[
    dict[str, dict[Profile, DomainSpec]],
    frozenset[str],
    dict[str, dict[Profile, frozenset[SqlType]]],
]:
    """도메인 이름 → 프로필별 명세, 겹치는 이름, 도메인 분류 → 프로필별 타입 모음."""
    pairs: list[tuple[str, dict[Profile, DomainSpec]]] = []
    class_types: dict[str, dict[Profile, set[SqlType]]] = {}
    for entry in map(domain_entry, rows):
        specs = {
            p: DomainSpec(
                entry["class"],
                SqlType(entry["postgres"][p]["type"]),
                entry["postgres"][p].get("length"),
                entry["postgres"][p].get("scale"),
            )
            for p in profiles
        }
        pairs.append((entry["name"], specs))
        for p, spec in specs.items():
            class_types.setdefault(spec.domain_class, {}).setdefault(p, set()).add(spec.type)
    domains, ambiguous = _unique(pairs)
    return (
        domains,
        ambiguous,
        {c: {p: frozenset(t) for p, t in by.items()} for c, by in class_types.items()},
    )


def _content_sha256(path: Path) -> str:
    """CRLF를 LF로 맞춘 내용의 sha256. 체크아웃 줄바꿈 설정이 달라도 같은 값이 나온다."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _unique[V](pairs: Iterable[tuple[str, V]]) -> tuple[dict[str, V], frozenset[str]]:
    """이름(NFC)별로 모은다. 같은 이름에 내용이 다른 항목이 있으면 그 이름은 따로 표시한다."""
    found: dict[str, V] = {}
    clashing: set[str] = set()
    for name, value in pairs:
        key = _nfc(name)
        if key in found and found[key] != value:
            clashing.add(key)
        found.setdefault(key, value)
    for key in clashing:
        del found[key]
    return found, frozenset(clashing)


def _nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


# ── 검사 ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ComplianceItem:
    """SC 항목 하나의 집계. 준수율은 진단한 칸이 없으면 None이다."""

    code: str
    total: int
    diagnosed: int
    compliant: int

    @property
    def undiagnosed(self) -> int:
        return self.total - self.diagnosed

    @property
    def rate(self) -> float | None:
        return self.compliant / self.diagnosed * 100 if self.diagnosed else None


class StandardComplianceReview(TypedDict):
    """검사 결과. `findings`·`requires_manual_review`는 정리 실패 변환기·#225와 같은 뜻이다."""

    findings: tuple[Finding, ...]
    requires_manual_review: bool
    items: tuple[ComplianceItem, ...]
    edition: str
    sha256: Mapping[str, str]


def compliance_severities(*, root: Path = DEFAULT_ROOT) -> dict[str, Severity]:
    """공통 팩 `rules.yaml` `standard_compliance`의 SC별 심각도. null인 항목은 뺀다.

    ADR-0010 SC 예외대로 SC에는 `critical`을 쓰지 않는다. 들어오면 SC 지적 하나로 최종 승인이
    막히므로 읽을 때 거절한다.
    """
    checks = load_common(root=root).rules.standard_compliance.checks
    critical = [c.id for c in checks if c.severity == Severity.CRITICAL]
    if critical:
        raise ValueError(
            f"표준 준수 검사에는 critical을 쓰지 않습니다 (ADR-0010 SC 예외): {', '.join(critical)}"
        )
    return {c.id: Severity(c.severity) for c in checks if c.severity is not None}


def pack_words(pack: str, *, root: Path = DEFAULT_ROOT) -> tuple[Word, ...]:
    """팩에 등록된 낱말: 공통 팩 `words.yaml` + 도메인 팩 `words.yaml` (뒤의 것이 우선)."""
    loaded = load_pack(pack, root=root)
    return (*loaded.common.words, *loaded.words)


@dataclass(frozen=True)
class _Context:
    """검사 한 번에 쓰는 사전들. 칸마다 다시 만들지 않는다."""

    official: OfficialStandard
    registered: Mapping[str, Word]  # 팩에 등록된 낱말
    forbidden: Mapping[str, str]  # 공식 금칙어 → 대신 쓸 공식 단어
    synonyms: Mapping[str, str]  # 공식 이음동의어 → 대신 쓸 공식 단어
    known: frozenset[str]  # 이름을 나눌 때 쓰는 낱말: 팩 낱말·공식 단어·공식 금칙어·이음동의어
    by_abbreviation: Mapping[str, tuple[str, ...]]  # 약어(대문자) → 그 약어를 쓰는 낱말
    severities: Mapping[str, Severity]
    profile: Profile
    iteration: int


@dataclass
class _Tally:
    """항목별 집계와 지적. `failed`는 부적합 칸이고, 지적 없이도 들어간다(SC-03과 겹친 SC-06)."""

    totals: dict[str, int]
    diagnosed: dict[str, int]
    failed: dict[str, set[str]]
    findings: list[Finding]

    def add(
        self, ctx: _Context, code: str, kind: str, column: Column, quote: str, suggestion: str
    ) -> None:
        severity = ctx.severities.get(code)
        if severity is None:
            raise ValueError(f"{code}의 심각도가 정해지지 않았습니다 (rules.yaml)")
        assert column.attribute_id is not None
        targets = (FindingTarget(kind="attribute", id=column.attribute_id),)
        self.failed[code].add(column.id)
        number = sum(1 for f in self.findings if f.rule_code == code) + 1
        self.findings.append(
            Finding(
                id=f"{code}-{ctx.iteration}-{number}",
                source=FindingSource.RULE,
                rule_code=code,
                kind=kind,
                severity=severity,
                targets=targets,
                evidence=({"quote": quote},),
                suggestion=suggestion,
                target_stage=None,
                fingerprint=fingerprint(code, kind, targets),
                iteration=ctx.iteration,
            )
        )


def check_standard_compliance(
    design: DesignState,
    *,
    official: OfficialStandard,
    words: Sequence[Word],
    severities: Mapping[str, Severity],
    profile: Profile,
    root: Path = DEFAULT_ROOT,
) -> StandardComplianceReview:
    """정리 결과(`design.normalized`)의 속성 칸을 SC-01~06으로 검사한다.

    `words`는 팩에 등록된 낱말(`pack_words`), `profile`은 `naming.yaml` `type_profile`이다.
    """
    model = design.normalized
    if model is None:
        raise ValueError("표준 준수 검사: 성공한 정리 결과가 없습니다")
    ctx = _context(official, words, severities, profile, design.iteration)
    tally = _Tally(dict.fromkeys(CODES, 0), dict.fromkeys(CODES, 0), {c: set() for c in CODES}, [])
    for table, column in _target_columns(model):
        for code in CODES:
            tally.totals[code] += 1
        where = f"{table.name}.{column.name}"
        name = _nfc(column.name)
        term = official.terms.get(name)
        parts = _split_name(name, term, ctx)
        _check_words(ctx, tally, column, where, parts)
        _check_classifier(ctx, tally, column, where, parts)
        if term is not None:
            _check_official_term(ctx, tally, column, where, name, term)
    policies = load_policies(root=root)
    routed = [apply_policy(f, policies) for f in tally.findings]
    items = tuple(
        ComplianceItem(
            c, tally.totals[c], tally.diagnosed[c], tally.diagnosed[c] - len(tally.failed[c])
        )
        for c in CODES
    )
    return StandardComplianceReview(
        findings=tuple(f for f, _ in routed),
        requires_manual_review=any(manual for _, manual in routed),
        items=items,
        edition=official.edition,
        sha256=dict(official.sha256),
    )


def _context(
    official: OfficialStandard,
    words: Sequence[Word],
    severities: Mapping[str, Severity],
    profile: Profile,
    iteration: int,
) -> _Context:
    registered = {_nfc(w.word): w for w in words}
    forbidden = official.forbidden_index()
    synonyms = official.synonym_index()
    by_abbreviation: dict[str, list[str]] = {}
    for name, info in official.words.items():
        by_abbreviation.setdefault(info.abbreviation.upper(), []).append(name)
    for name, word in registered.items():
        by_abbreviation.setdefault(word.abbreviation.upper(), []).append(name)
    return _Context(
        official=official,
        registered=registered,
        forbidden=forbidden,
        synonyms=synonyms,
        known=frozenset(
            {*registered, *official.words, *official.ambiguous_words, *forbidden, *synonyms}
        ),
        by_abbreviation={k: tuple(dict.fromkeys(v)) for k, v in by_abbreviation.items()},
        severities=severities,
        profile=profile,
        iteration=iteration,
    )


def _target_columns(model: NormalizedModel) -> list[tuple[Table, Column]]:
    """팩 용어가 아닌 속성에서 온 칸. 팩 용어 칸은 A03·RULE-03이, FK 칸은 부모 칸이 본다."""
    return sorted(
        (
            (table, c)
            for table in model.tables
            for c in table.columns
            if c.attribute_id is not None and c.domain is None
        ),
        key=lambda pair: (pair[0].id, pair[1].id),
    )


def _split_name(name: str, term: OfficialTerm | None, ctx: _Context) -> tuple[str, ...] | None:
    """공식 용어와 이름이 같으면 그 약어의 단어 경계로, 아니면 끝에서부터 긴 단어 먼저 나눈다.

    공식 용어는 약어가 단어 경계를 담고 있다(보고서명 = RPTP_NM = 보고서+명). 끝에서부터 나누면
    보고+서명처럼 분류어가 아닌 끝 단어가 나와 SC-02가 잘못 날 수 있다(#247 리뷰).
    """
    if term is not None:
        split = split_by_abbreviation(name, term.abbreviation, ctx.by_abbreviation)
        if split is not None:
            return split
    return split_from_end(name, ctx.known)


def _check_words(
    ctx: _Context, tally: _Tally, column: Column, where: str, parts: tuple[str, ...] | None
) -> None:
    """SC-01 팩 낱말·공식 단어로 나눌 수 없는 부분, SC-04 팩에 없는 공식 금칙어·이음동의어."""
    tally.diagnosed["SC-01"] += 1
    if parts is None:
        tally.add(
            ctx,
            "SC-01",
            "unregistered_word",
            column,
            f"{where}: 이름을 팩 사전·공통표준 단어로 끝까지 나눌 수 없습니다.",
            "공통표준 단어로 바꾸거나 팩 사전에 낱말을 등록한다.",
        )
        return
    tally.diagnosed["SC-04"] += 1
    for word in dict.fromkeys(parts):
        # 팩에 등록한 낱말은 팩 리뷰를 거친 의도한 선택이라 지적하지 않는다 (R2 11/9, R1 #247)
        if word in ctx.forbidden and word not in ctx.registered:
            instead = ctx.forbidden[word]
            tally.add(
                ctx,
                "SC-04",
                f"forbidden_word:{word}",
                column,
                f"{where}: 「{word}」는 공통표준 금칙어입니다(대신 「{instead}」).",
                f"「{instead}」로 바꿀지, 팩에 낱말을 등록할지 정한다.",
            )
        elif word in ctx.synonyms and word not in ctx.registered:
            # 심각도·처리는 rules.yaml subtypes.synonym(minor·참고)이 정한다 (#260)
            instead = ctx.synonyms[word]
            tally.add(
                ctx,
                "SC-04",
                f"synonym:{word}",
                column,
                f"{where}: 「{word}」는 공통표준 단어 「{instead}」의 이음동의어입니다.",
                f"표준어 「{instead}」로 바꾸는 것을 검토한다.",
            )


def _check_classifier(
    ctx: _Context, tally: _Tally, column: Column, where: str, parts: tuple[str, ...] | None
) -> None:
    """SC-02 끝 단어가 분류어가 아님, SC-03 분류어의 도메인 분류와 칸 타입이 다름."""
    last = _word_info(parts[-1], ctx.registered, ctx.official) if parts else None
    if last is None:
        return
    word, is_classifier, group = last
    tally.diagnosed["SC-02"] += 1
    if not is_classifier:
        tally.add(
            ctx,
            "SC-02",
            "missing_classifier",
            column,
            f"{where}: 끝 단어 「{word}」가 분류어(형식단어)가 아닙니다.",
            "이름 끝에 분류어(예: 코드·명·일자·번호)를 둔다.",
        )
        return
    types = ctx.official.class_types.get(group or "", {}).get(ctx.profile, frozenset())
    if not types:
        return
    tally.diagnosed["SC-03"] += 1
    if column.data_type not in types:
        allowed = "·".join(sorted(t.value for t in types))
        tally.add(
            ctx,
            "SC-03",
            "classifier_domain_mismatch",
            column,
            f"{where}: 분류어 「{word}」의 도메인 분류 {group}은 {ctx.profile} 기준 "
            f"{allowed}인데 칸 타입은 {column.data_type.value}입니다.",
            f"{group} 도메인의 타입으로 바꾼다.",
        )


def _check_official_term(
    ctx: _Context, tally: _Tally, column: Column, where: str, name: str, term: OfficialTerm
) -> None:
    """SC-05 공식 용어와 약어가 다름, SC-06 그 도메인과 타입·길이·소수 자릿수가 다름."""
    tally.diagnosed["SC-05"] += 1
    if column.physical_name.upper() != term.abbreviation.upper():
        tally.add(
            ctx,
            "SC-05",
            "official_term_conflict",
            column,
            f"{where}: 공통표준 용어와 이름이 같은데 약어가 다릅니다 "
            f"({column.physical_name.upper()} ≠ 공식 {term.abbreviation}).",
            "팩에 공식 용어를 등록할지, 이름을 바꿀지 정한다.",
        )
    spec = ctx.official.domains.get(_nfc(term.domain), {}).get(ctx.profile)
    if spec is None:
        return
    tally.diagnosed["SC-06"] += 1
    differs = _spec_differences(column, spec)
    if differs and column.id in tally.failed["SC-03"]:
        # 타입 문제는 SC-03으로 이미 지적했다. 지적은 다시 내지 않지만, 공식 도메인과 다르므로
        # SC-06 집계에서는 부적합으로 센다(적합으로 세면 준수율이 부풀려진다).
        tally.failed["SC-06"].add(column.id)
    elif differs:
        tally.add(
            ctx,
            "SC-06",
            "type_length_mismatch",
            column,
            f"{where}: 공통표준 용어 {name}의 도메인 {term.domain}({ctx.profile} 기준 "
            f"{_describe(spec)})과 다릅니다: {', '.join(differs)}.",
            f"{term.domain}의 타입·길이로 바꾼다.",
        )


def split_by_abbreviation(
    name: str, abbreviation: str, by_abbreviation: Mapping[str, Collection[str]]
) -> tuple[str, ...] | None:
    """공식 약어의 `_` 경계대로 이름을 나눈다(보고서명 + RPTP_NM → 보고서+명). 안 맞으면 None.

    약어 조각마다 그 약어를 쓰는 낱말 중 이름의 남은 앞부분과 맞는 것을 고른다. 여러 분할이 맞으면
    앞 조각부터 차례로 가장 긴 낱말을 고른다(예: ab·a / c·bcd / def·ef로 abcdef → ab+c+def). 먼저
    뒤에서부터 「이 조각부터 끝까지 맞출 수 있는 위치」를 구해 두고, 앞에서부터 그 위치로 이어지는
    가장 긴 낱말을 고른다. 공백은 무시한다.
    """
    text = "".join(_nfc(name).split())
    pieces = [p for p in abbreviation.upper().split("_") if p]
    candidates = [sorted(by_abbreviation.get(p, ()), key=len, reverse=True) for p in pieces]
    # finishes[i]: 조각 i부터 끝까지 맞출 수 있는 시작 위치들
    finishes: list[set[int]] = [set() for _ in range(len(pieces) + 1)]
    finishes[len(pieces)] = {len(text)}
    for i in range(len(pieces) - 1, -1, -1):
        finishes[i] = {
            stop - len(word)
            for stop in finishes[i + 1]
            for word in candidates[i]
            if len(word) <= stop and text.startswith(word, stop - len(word))
        }
    if 0 not in finishes[0]:
        return None
    parts: list[str] = []
    position = 0
    for i, words in enumerate(candidates):
        word = next(
            w
            for w in words
            if text.startswith(w, position) and position + len(w) in finishes[i + 1]
        )
        parts.append(word)
        position += len(word)
    return tuple(parts)


def split_from_end(name: str, words: Collection[str]) -> tuple[str, ...] | None:
    """이름을 사전 단어로 끝에서부터, 긴 단어를 먼저 맞춰 나눈다. 끝까지 못 나누면 None.

    `common/RATIONALE.md` 「표준 준수 진단」 SC-01 기준이다(「주민등록번호」를 「번호」로 먼저
    쪼개지 않는다). 남은 앞부분을 나눌 수 없으면 한 단계 짧은 단어로 다시 맞춘다. 공백은 단어
    경계로 본다. 물리명 만들기(`codegen/naming.py`)는 조각 수가 가장 적은 분할을 쓰므로 둘이 다를 수
    있다(예: 「가산금리」를 이 함수는 가산+금리, 물리명은 가산금+리로 나눈다).
    """
    longest = max((len(w) for w in words), default=0)
    parts: list[str] = []
    for chunk in _nfc(name).split():
        split = _split_chunk(chunk, words, longest)
        if split is None:
            return None
        parts.extend(split)
    return tuple(parts) if parts else None


def _split_chunk(text: str, words: Collection[str], longest: int) -> tuple[str, ...] | None:
    """`text`를 끝에서부터 나눈다. 재귀 없이 앞에서부터 위치별 선택만 적어 둔다.

    `start_of[end]`는 앞 `end`글자를 나눌 수 있을 때 마지막 단어의 시작 위치다. 위치마다 가장 긴 끝
    단어(가장 앞의 시작 위치)부터 보고, 그 앞부분이 나뉘는 첫 위치를 고른다. 그래서 「끝 단어를 가장
    길게 잡고, 앞부분이 안 풀리면 한 단계 짧게」와 같은 결과이고, 메모리는 이름 길이에 비례한다.
    """
    size = len(text)
    start_of: list[int | None] = [None] * (size + 1)
    start_of[0] = 0  # 빈 앞부분은 나뉜 것으로 본다
    for end in range(1, size + 1):
        for begin in range(max(0, end - longest), end):  # 앞에서 시작할수록 긴 끝 단어
            if start_of[begin] is not None and text[begin:end] in words:
                start_of[end] = begin
                break
    if start_of[size] is None:
        return None
    pieces: list[str] = []
    end = size
    while end > 0:
        first = start_of[end]
        assert first is not None
        pieces.append(text[first:end])
        end = first
    return tuple(reversed(pieces))


def _word_info(
    word: str, registered: Mapping[str, Word], official: OfficialStandard
) -> tuple[str, bool, str | None] | None:
    """(단어, 분류어 여부, 도메인 분류). 금칙어처럼 단어 정보가 없거나 이름이 겹치면 None."""
    if word in registered:
        found = registered[word]
        return found.word, found.is_classifier, found.domain_group
    if word in official.words:
        info = official.words[word]
        return word, info.is_classifier, info.domain_group
    return None


def _spec_differences(column: Column, spec: DomainSpec) -> list[str]:
    """칸과 도메인 명세의 차이. 시각 소수 초 자릿수는 보지 않는다(속성 계약에 칸이 없음)."""
    if column.data_type is not spec.type:
        return [f"타입 {column.data_type.value} ≠ {spec.type.value}"]
    differs: list[str] = []
    if spec.type is SqlType.NUMERIC:
        pairs: tuple[tuple[str, Any, Any], ...] = (
            ("정밀도", column.precision, spec.length),
            ("소수 자릿수", column.scale or 0, spec.scale or 0),
        )
    elif spec.type in (SqlType.CHAR, SqlType.VARCHAR):
        pairs = (("길이", column.length, spec.length),)
    else:
        pairs = ()
    differs.extend(f"{label} {mine} ≠ {theirs}" for label, mine, theirs in pairs if mine != theirs)
    return differs


def _describe(spec: DomainSpec) -> str:
    if spec.type is SqlType.NUMERIC:
        return f"numeric({spec.length},{spec.scale or 0})"
    if spec.type in (SqlType.CHAR, SqlType.VARCHAR):
        return f"{spec.type.value}({spec.length})"
    return spec.type.value
