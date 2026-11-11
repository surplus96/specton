"""도메인 팩 로더 (#11, docs/10 "도메인 팩").

팩 폴더(`domain_packs/<pack>/`)의 파일을 Pydantic 모델로 읽고 검증한다.
팩 위치는 `root` 인자 한 곳에서 받는다.

- 선택할 수 있는 팩은 `manifest.yaml`이 있는 폴더 중 `common`을 뺀 것이다.
  `common`은 모든 팩이 함께 쓰는 공통 기반이라 사용자가 고르지 않는다.
- 팩 이름은 영문 소문자·숫자·`_`만 받는다. `../` 같은 경로가 섞인 이름은 폴더를 찾기 전에 거절한다.
- `naming.yaml`·`rules.yaml`의 일부 값은 아직 정하지 않아 `null`이다(미정값). manifest의
  `status`가 `draft`면 미정값을 둬도 된다. approved는 심각도·처리 방식을 확정해야 한다.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from specton.contracts.base import SqlType, TargetStage
from specton.contracts.findings import Severity
from specton.packs.build import DEFAULT_ROOT
from specton.packs.term_names import term_name_conflicts

COMMON = "common"
PACK_NAME = r"^[a-z][a-z0-9_]*$"
PackName = Annotated[str, StringConstraints(pattern=PACK_NAME)]
Version = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class PackError(ValueError):
    """팩 폴더나 파일이 없거나 형식이 틀렸다."""


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Manifest(_Strict):
    """팩 정보. name·version은 실행(run)에 기록한다."""

    name: PackName
    version: Version
    description: NonEmpty
    source: NonEmpty
    origin: Literal["synthetic", "public", "approved"]
    status: Literal["draft", "approved"]
    lexicon_sources: Literal["lexicon_sources.yaml"] | None = None


class Word(_Strict):
    """표준단어 하나(공통표준 또는 팩 전용). `is_classifier`가 true면 용어의 분류어로 쓸 수 있다."""

    word: NonEmpty
    abbreviation: NonEmpty
    english: NonEmpty
    definition: NonEmpty
    is_classifier: bool
    domain_group: str | None = None
    synonyms: tuple[str, ...] = ()
    forbidden_synonyms: tuple[str, ...] = ()


class PgType(_Strict):
    """도메인 하나를 PostgreSQL로 옮긴 타입 명세. 필드는 타입에 따라 일부만 쓴다."""

    type: SqlType
    length: int | None = None
    scale: int | None = None
    precision: int | None = None
    check: str | None = None


class PostgresMapping(_Strict):
    """같은 도메인의 두 PostgreSQL 매핑. strict는 표준 저장 형식, pg_native는 고유 타입을 쓴다."""

    strict: PgType
    pg_native: PgType


class Domain(_Strict):
    """표준도메인 하나. `class`는 파이썬 예약어가 아니라 필드 이름으로 못 써 별칭을 쓴다."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", str_strip_whitespace=True, populate_by_name=True
    )

    group: NonEmpty
    domain_class: NonEmpty = Field(alias="class")
    name: NonEmpty
    standard_type: NonEmpty
    length: int | None = None
    scale: int | None = None
    storage_format: str | None = None
    allowed_values: str | None = None
    postgres: PostgresMapping


class _PhysicalNameRule(_Strict):
    unresolved: Literal["error", "technical_id"] = "error"
    dictionary_case: NonEmpty
    ddl_case: NonEmpty
    word_separator: NonEmpty
    max_bytes: int


class _AbbreviationRule(_Strict):
    case: NonEmpty
    min_length: int
    max_length: int


class _TermRule(_Strict):
    word_aliases: Literal["disabled", "official_unambiguous"] = "disabled"
    classifier_last: bool
    # 기본값을 두지 않는다: 미정값은 키를 생략하지 못하고 null을 적어야 한다
    max_words: Literal["unlimited"] | None
    official_term_immutable: bool


class _TableRule(_Strict):
    prefix: Literal["none"] | None  # 기본값 없음(위와 같은 이유). "none" = 접두어 없음, null = 미정
    form: Literal["as_dictionary"] | None
    junction_name: Literal["parent_child"] | None  # 기본값 없음(위와 같은 이유)


class _ColumnRule(_Strict):
    repeated_foreign_key: Literal["manual", "relationship_id"] = "manual"
    primary_key: Literal["term_physical_name"] | None  # 기본값 없음(위와 같은 이유)
    foreign_key: Literal["parent_key_physical_name"] | None
    # 기본값 없음(위와 같은 이유). 값은 words.yaml의 표준단어(예: 상위)
    self_reference_prefix: str | None


class Naming(_Strict):
    """명명 규칙. `term.max_words`·`table.*`·`column.*`는 아직 정하지 않으면 null이다(미정값)."""

    physical_name: _PhysicalNameRule
    abbreviation: _AbbreviationRule
    term: _TermRule
    table: _TableRule
    column: _ColumnRule
    type_profile: Literal["strict", "pg_native"]
    reserved_words_source: NonEmpty


class RulePolicy(_Strict):
    """null인 복귀 단계의 의미를 명시한다. 옛 초안의 handling 생략은 미정으로 남긴다."""

    severity: Severity | None
    target_stage: TargetStage | None
    handling: Literal["fixed", "dynamic", "manual", "informational"] | None = None

    @property
    def resolved_handling(self) -> str | None:
        return self.handling or ("fixed" if self.target_stage is not None else None)

    @model_validator(mode="after")
    def consistent_policy(self) -> "RulePolicy":
        if self.handling == "fixed" and self.target_stage is None:
            raise ValueError("fixed 처리에는 target_stage가 필요합니다")
        if (
            self.handling in {"dynamic", "manual", "informational"}
            and self.target_stage is not None
        ):
            raise ValueError("dynamic/manual/informational 처리의 target_stage는 null이어야 합니다")
        if self.handling == "informational" and self.severity != Severity.MINOR:
            raise ValueError("informational 처리는 minor만 허용합니다")
        return self


class Rule(RulePolicy):
    """필수 설계 규칙. dynamic은 대상·문제 세부 유형으로 복귀 단계를 계산한다."""

    id: NonEmpty
    name: NonEmpty
    subtypes: dict[NonEmpty, RulePolicy] = Field(default_factory=dict)


class ComplianceCheck(RulePolicy):
    """표준 준수 정책. SC-04 synonym처럼 별도 심각도가 필요한 유형을 명시할 수 있다."""

    id: NonEmpty
    name: NonEmpty
    subtypes: dict[NonEmpty, RulePolicy] = Field(default_factory=dict)

    @model_validator(mode="after")
    def no_critical(self) -> "ComplianceCheck":
        if any(p.severity == Severity.CRITICAL for p in (self, *self.subtypes.values())):
            raise ValueError(
                f"표준 준수 검사에는 critical을 쓰지 않습니다 (ADR-0010 SC 예외): {self.id}"
            )
        return self


class StandardCompliance(_Strict):
    checks: tuple[ComplianceCheck, ...]
    compliance_rate: NonEmpty


class Rules(_Strict):
    """규칙 검사 설정 (#15, docs/04 "규칙 검사")."""

    rules: tuple[Rule, ...]
    standard_compliance: StandardCompliance
    crud_exemption_reasons: dict[NonEmpty, tuple[Literal["C", "R", "U", "D"], ...]]


class Term(_Strict):
    """팩 용어 하나. composition은 Word.word를 조합 순서대로 적은 것이다."""

    term: NonEmpty
    composition: tuple[NonEmpty, ...]
    domain: NonEmpty
    physical_name: NonEmpty
    source: Literal["official", "project"]
    synonyms: tuple[str, ...] = ()


class Pattern(_Strict):
    """도메인 설계 패턴 하나. suggests는 패턴마다 모양이 달라 자유 형식으로 둔다."""

    id: NonEmpty
    name: NonEmpty
    when: NonEmpty
    suggests: dict[str, Any]
    source: NonEmpty


class ErdAreaSpec(_Strict):
    """ERD 업무 영역 하나 (#13). 엔티티 한글 이름에 낱말이 들어 있으면 이 영역 후보다.

    배정 규칙(가장 긴 낱말 우선, 같으면 먼저 적힌 영역)과 「기타」·낱말 겹침 검사는
    `specton/codegen/erd_areas.py`가 맡는다. 여기서는 파일 모양만 본다.
    """

    name: NonEmpty
    words: tuple[NonEmpty, ...] = Field(min_length=1)


class _ErdAreasFile(_Strict):
    areas: tuple[ErdAreaSpec, ...] = Field(min_length=1)


class _CommonWordsFile(_Strict):
    edition: NonEmpty
    words: tuple[Word, ...]


class _CommonDomainsFile(_Strict):
    edition: NonEmpty
    allowed_sql_types: tuple[SqlType, ...]
    domains: tuple[Domain, ...]
    on_unknown: Literal["finding"]


class _PackWordsFile(_Strict):
    words: tuple[Word, ...] = ()


class _TermsFile(_Strict):
    terms: tuple[Term, ...]


class _PatternsFile(_Strict):
    patterns: tuple[Pattern, ...]


@dataclass(frozen=True)
class Common:
    """공통 팩(`domain_packs/common/`)을 읽은 결과. 모든 팩이 이것을 함께 쓴다."""

    manifest: Manifest
    words: tuple[Word, ...]
    domains: tuple[Domain, ...]
    naming: Naming
    rules: Rules


@dataclass(frozen=True)
class Pack:
    """팩 하나를 읽은 결과. common은 그 팩이 쓰는 공통 팩이다."""

    manifest: Manifest
    common: Common
    terms: tuple[Term, ...]
    words: tuple[Word, ...]
    patterns: tuple[Pattern, ...]


def available_packs(*, root: Path = DEFAULT_ROOT) -> tuple[str, ...]:
    """사용자가 고를 수 있는 팩 이름 목록(가나다순이 아니라 영문 이름순)."""
    names = (p.parent.name for p in root.glob("*/manifest.yaml"))
    return tuple(sorted(n for n in names if n != COMMON))


def load_manifest(pack: str, *, root: Path = DEFAULT_ROOT) -> Manifest:
    """팩의 manifest를 읽어 검증한다. manifest의 name이 폴더 이름과 달라도 거절한다."""
    path = _pack_dir(pack, root) / "manifest.yaml"
    manifest = _validate(Manifest, path)
    if manifest.name != pack:
        raise PackError(f"{path}: name({manifest.name})이 폴더 이름({pack})과 다릅니다")
    return manifest


def load_common(*, root: Path = DEFAULT_ROOT) -> Common:
    """공통 팩을 읽는다. approved인데 미정값(null)이 남아 있으면 모두 모아 한 번에 거절한다."""
    manifest = load_manifest(COMMON, root=root)
    folder = root / COMMON
    words = _validate(_CommonWordsFile, folder / "words.yaml").words
    domains = _validate(_CommonDomainsFile, folder / "domains.yaml").domains
    naming = _validate(Naming, folder / "naming.yaml")
    rules = _validate(Rules, folder / "rules.yaml")
    _check_blanks(manifest, folder, _naming_blanks(naming) + _rules_blanks(rules))
    _check_selection(folder, root, words)
    return Common(manifest=manifest, words=words, domains=domains, naming=naming, rules=rules)


def load_pack(pack: str, *, root: Path = DEFAULT_ROOT) -> Pack:
    """팩 하나를 공통 팩과 함께 읽는다. 용어의 domain은 공통 도메인 중 하나여야 한다."""
    if pack == COMMON:
        raise PackError(f"{COMMON}은 선택할 수 있는 팩이 아닙니다")
    manifest = load_manifest(pack, root=root)
    common = load_common(root=root)
    folder = root / pack
    words = _validate(_PackWordsFile, folder / "words.yaml").words
    from specton.packs.lexicon_sources import LexiconSourceError, validate_lexicon_sources

    try:
        validate_lexicon_sources(folder)
    except LexiconSourceError as exc:
        raise PackError(str(exc)) from exc
    terms_path = folder / "terms.yaml"
    raw_terms = _read_data(terms_path)
    terms = _parse(_TermsFile, raw_terms, terms_path).terms
    # 사용자 지정 팩은 빌드를 거치지 않을 수 있어 로더도 빌드와 같은 이름 검사를 한다 (#264).
    # 모델(_Strict)은 앞뒤 공백을 지우므로, 원인을 빌드와 같게 안내하려고 원본 값을 넘긴다.
    # 모델 검증을 통과한 뒤라 원본도 term·synonyms가 문자열인 모양이다.
    raw_names = ((t["term"], t.get("synonyms") or ()) for t in raw_terms["terms"])
    if problems := term_name_conflicts(raw_names):
        raise PackError(f"{terms_path}:\n" + "\n".join(problems))
    patterns = _validate(_PatternsFile, folder / "patterns.yaml").patterns
    domain_names = {d.name for d in common.domains}
    unknown = sorted({t.domain for t in terms if t.domain not in domain_names})
    if unknown:
        raise PackError(f"{folder / 'terms.yaml'}: 공통 도메인에 없는 domain {unknown}")
    _check_selection(folder, root, words)
    return Pack(manifest=manifest, common=common, terms=terms, words=words, patterns=patterns)


def _check_selection(folder: Path, root: Path, words: tuple[Word, ...]) -> None:
    sources = root / "sources/sources.yaml"
    if sources.is_file():
        from specton.packs.build import BuildError, read_csv, read_yaml, word_entry
        from specton.packs.selection import validate_selection

        spec = read_yaml(sources)["files"]["words"]
        try:
            validate_selection(
                folder,
                map(word_entry, read_csv(sources.parent / spec["path"])),
                registered_words=(word.word for word in words),
            )
        except BuildError as exc:
            raise PackError(str(exc)) from exc


def load_erd_areas(pack: str, *, root: Path = DEFAULT_ROOT) -> tuple[ErdAreaSpec, ...]:
    """팩의 `erd_areas.yaml`(ERD 업무 영역, #13)을 읽는다. 파일이 없으면 빈 목록이다.

    영역이 없으면 PDF는 영역을 나누지 않고 전체 상세도 하나로 그린다. 그래서 다른 팩 파일과 달리
    없어도 오류가 아니다. `load_pack`과 따로 두어, 영역을 쓰지 않는 노드는 이 파일을 읽지 않는다.
    """
    if pack == COMMON:
        raise PackError(f"{COMMON}은 선택할 수 있는 팩이 아닙니다")
    load_manifest(pack, root=root)  # 팩 이름·폴더 검사
    path = root / pack / "erd_areas.yaml"
    if not path.is_file():
        return ()
    return _validate(_ErdAreasFile, path).areas


def _naming_blanks(naming: Naming) -> list[str]:
    """naming.yaml에서 아직 정하지 않은 값(미정값)의 경로 목록.

    null과 빈 문자열을 미정값으로 본다(#151 기준). 공백만 있는 값은 `str_strip_whitespace`로
    읽을 때 빈 문자열이 되므로 여기서 함께 걸린다.
    """
    fields = {
        "term.max_words": naming.term.max_words,
        "table.prefix": naming.table.prefix,
        "table.form": naming.table.form,
        "table.junction_name": naming.table.junction_name,
        "column.primary_key": naming.column.primary_key,
        "column.foreign_key": naming.column.foreign_key,
        "column.self_reference_prefix": naming.column.self_reference_prefix,
    }
    return [path for path, value in fields.items() if value is None or value == ""]


def _rules_blanks(rules: Rules) -> list[str]:
    """심각도와 처리 방식의 미정값만 거절한다. 의도적으로 비운 복귀 단계는 허용한다."""
    policies: list[tuple[str, RulePolicy]] = [(f"rules.{r.id}", r) for r in rules.rules]
    for rule in rules.rules:
        policies.extend((f"rules.{rule.id}.subtypes.{k}", p) for k, p in rule.subtypes.items())
    for check in rules.standard_compliance.checks:
        prefix = f"standard_compliance.{check.id}"
        policies.append((prefix, check))
        policies.extend((f"{prefix}.subtypes.{kind}", p) for kind, p in check.subtypes.items())
    blanks = []
    for path, policy in policies:
        if policy.severity is None:
            blanks.append(f"{path}.severity")
        if policy.resolved_handling is None:
            blanks.append(f"{path}.target_stage (handling 미정)")
    return blanks


def _check_blanks(manifest: Manifest, folder: Path, blanks: list[str]) -> None:
    if blanks and manifest.status == "approved":
        raise PackError(f"{folder}: approved인데 미정값(null)이 남아 있습니다: {blanks}")


def _pack_dir(pack: str, root: Path) -> Path:
    if not re.fullmatch(PACK_NAME, pack):
        raise PackError(f"팩 이름은 영문 소문자·숫자·_만 씁니다: {pack!r}")
    folder = root / pack
    if not (folder / "manifest.yaml").is_file():
        raise PackError(f"팩이 없습니다: {pack} (위치 {root})")
    return folder


def _validate[ModelT: BaseModel](model: type[ModelT], path: Path) -> ModelT:
    return _parse(model, _read_data(path), path)


def _read_data(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:  # 파일 없음·폴더·권한·인코딩도 PackError 하나로
        raise PackError(f"{path}: 팩 파일을 읽지 못했습니다 ({type(exc).__name__})") from exc
    try:
        return yaml.load(text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise PackError(f"{path}: 형식이 틀렸습니다\n{exc}") from exc


def _parse[ModelT: BaseModel](model: type[ModelT], data: Any, path: Path) -> ModelT:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise PackError(f"{path}: 형식이 틀렸습니다\n{exc}") from exc
