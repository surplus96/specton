"""도메인 팩 로더 (#11, docs/10 "도메인 팩").

팩 폴더(`domain_packs/<pack>/`)의 파일을 Pydantic 모델로 읽고 검증한다.
팩 위치는 `root` 인자 한 곳에서 받는다.

- 선택할 수 있는 팩은 `manifest.yaml`이 있는 폴더 중 `common`을 뺀 것이다.
  `common`은 모든 팩이 함께 쓰는 공통 기반이라 사용자가 고르지 않는다.
- 팩 이름은 영문 소문자·숫자·`_`만 받는다. `../` 같은 경로가 섞인 이름은 폴더를 찾기 전에 거절한다.
- `naming.yaml`·`rules.yaml`의 일부 값은 아직 정하지 않아 `null`이다(미정값). manifest의
  `status`가 `draft`면 미정값을 둬도 되고, `approved`면 모두 채워야 한다 — `load_common`이 검사한다.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from specton.contracts.base import SqlType, TargetStage
from specton.contracts.findings import Severity
from specton.packs.build import DEFAULT_ROOT

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
    dictionary_case: NonEmpty
    ddl_case: NonEmpty
    word_separator: NonEmpty
    max_bytes: int


class _AbbreviationRule(_Strict):
    case: NonEmpty
    min_length: int
    max_length: int


class _TermRule(_Strict):
    classifier_last: bool
    # 기본값을 두지 않는다: 미정값은 키를 생략하지 못하고 null을 적어야 한다
    max_words: Literal["unlimited"] | None
    official_term_immutable: bool


class _TableRule(_Strict):
    prefix: Literal["none"] | None  # 기본값 없음(위와 같은 이유). "none" = 접두어 없음, null = 미정
    form: Literal["as_dictionary"] | None
    junction_name: Literal["parent_child"] | None  # 기본값 없음(위와 같은 이유)


class _ColumnRule(_Strict):
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


class Rule(_Strict):
    """규칙 검사 하나. severity·target_stage는 #15에서 정하기 전까지 null이다(미정값).

    기본값을 두지 않는다: 키를 생략하지 못하고 미정이면 `null`을 적어야 한다(그래야
    "쓰다가 빠뜨림"과 "아직 정하지 않음"이 구분된다).
    """

    id: NonEmpty
    name: NonEmpty
    severity: Severity | None
    target_stage: TargetStage | None


class ComplianceCheck(_Strict):
    """데이터 표준 준수 검사 하나. severity·target_stage는 #15 착수 전까지 null이다(미정값).

    기본값 없음(Rule과 같은 이유).
    """

    id: NonEmpty
    name: NonEmpty
    severity: Severity | None
    target_stage: TargetStage | None


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
    return Common(manifest=manifest, words=words, domains=domains, naming=naming, rules=rules)


def load_pack(pack: str, *, root: Path = DEFAULT_ROOT) -> Pack:
    """팩 하나를 공통 팩과 함께 읽는다. 용어의 domain은 공통 도메인 중 하나여야 한다."""
    if pack == COMMON:
        raise PackError(f"{COMMON}은 선택할 수 있는 팩이 아닙니다")
    manifest = load_manifest(pack, root=root)
    common = load_common(root=root)
    folder = root / pack
    words = _validate(_PackWordsFile, folder / "words.yaml").words
    terms = _validate(_TermsFile, folder / "terms.yaml").terms
    patterns = _validate(_PatternsFile, folder / "patterns.yaml").patterns
    domain_names = {d.name for d in common.domains}
    unknown = sorted({t.domain for t in terms if t.domain not in domain_names})
    if unknown:
        raise PackError(f"{folder / 'terms.yaml'}: 공통 도메인에 없는 domain {unknown}")
    return Pack(manifest=manifest, common=common, terms=terms, words=words, patterns=patterns)


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
    """rules.yaml에서 아직 정하지 않은 값(미정값)의 경로 목록."""
    blanks = []
    for rule in rules.rules:
        if rule.severity is None:
            blanks.append(f"rules.{rule.id}.severity")
        if rule.target_stage is None:
            blanks.append(f"rules.{rule.id}.target_stage")
    for check in rules.standard_compliance.checks:
        if check.severity is None:
            blanks.append(f"standard_compliance.{check.id}.severity")
        if check.target_stage is None:
            blanks.append(f"standard_compliance.{check.id}.target_stage")
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
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:  # 파일 없음·폴더·권한·인코딩도 PackError 하나로
        raise PackError(f"{path}: 팩 파일을 읽지 못했습니다 ({type(exc).__name__})") from exc
    try:
        data = yaml.safe_load(text)
        return model.model_validate(data)
    except (yaml.YAMLError, ValidationError) as exc:
        raise PackError(f"{path}: 형식이 틀렸습니다\n{exc}") from exc
