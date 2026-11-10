"""운영 팩 확장 어휘의 출처·선정 근거를 오프라인으로 검증한다 (#291).

기존 팩은 manifest에 lexicon_sources가 없으면 그대로 읽는다. 선언한 팩은
고정 기준 사본과 달라진 모든 단어를 공개 원본의 행·영문·약어에 대조한다.
평가 원문·정답을 읽거나 사전을 자동 보완하지 않는다.
"""

import csv
import hashlib
import io
import unicodedata
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from specton.packs.build import BuildError, read_yaml

Text = Annotated[str, StringConstraints(min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CATALOG = "lexicon_sources.yaml"


class LexiconSourceError(BuildError):
    """출처가 없거나 기록·원본·실제 사전이 일치하지 않는다."""


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Artifact(_Strict):
    path: Text
    sha256: Sha256
    hash_mode: Literal["raw_bytes"]


class Baseline(Artifact):
    version: Text
    ref: Text


class Source(Artifact):
    edition: Text
    publisher: Text
    url: Text
    license: Literal["이용허락범위 제한 없음"]
    retrieved_on: date
    encoding: Literal["cp949", "utf-8-sig"]
    word_column: Text
    english_column: Text
    abbreviation_column: Text


class Candidate(_Strict):
    word: Text
    decision: Literal["include", "exclude"]
    reason: Text
    source: str | None = None
    row: int | None = Field(default=None, ge=2)
    definition_basis: str | None = None


class Selection(_Strict):
    policy_version: Text
    scope: Text
    input_basis: Literal["development"]
    criteria: tuple[Text, ...] = Field(min_length=1)
    review_ref: Text


class Catalog(_Strict):
    schema_version: Literal[1]
    pack: Text
    baseline: Baseline
    selection: Selection
    sources: dict[Text, Source] = Field(min_length=1)
    candidates: tuple[Candidate, ...] = Field(min_length=1)


def _name(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip())


def _path(folder: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise LexiconSourceError("출처 경로는 팩 내부 상대경로여야 합니다")
    resolved = (folder / path).resolve()
    if not resolved.is_relative_to(folder.resolve()):
        raise LexiconSourceError("출처 경로가 팩 폴더를 벗어납니다")
    return resolved


def _verified(folder: Path, artifact: Artifact) -> bytes:
    path = _path(folder, artifact.path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise LexiconSourceError(f"출처 사본을 읽을 수 없습니다: {artifact.path}") from exc
    if hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise LexiconSourceError(f"출처 sha256 불일치: {artifact.path}")
    return data


def _words(data: dict[str, Any], where: str) -> dict[str, dict[str, Any]]:
    rows = data.get("words")
    if not isinstance(rows, list):
        raise LexiconSourceError(f"{where}: words 목록이 필요합니다")
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("word"), str):
            raise LexiconSourceError(f"{where}: 단어 형식이 잘못됐습니다")
        word = _name(row["word"])
        if not word or word in found:
            raise LexiconSourceError(f"{where}: 빈 이름 또는 NFC 중복 단어 {word}")
        found[word] = row
    return found


def _rows(folder: Path, source: Source) -> list[dict[str, str]]:
    if not source.url.startswith("https://"):
        raise LexiconSourceError("출처 URL은 https여야 합니다")
    try:
        text = _verified(folder, source).decode(source.encoding)
        reader = csv.DictReader(io.StringIO(text, newline=""))
        required = {source.word_column, source.english_column, source.abbreviation_column}
        if not required <= set(reader.fieldnames or ()):
            raise LexiconSourceError("출처 CSV의 단어·영문·약어 열이 없습니다")
        rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise LexiconSourceError(f"출처 CSV를 읽을 수 없습니다: {source.path}") from exc
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise LexiconSourceError(f"출처 CSV 행의 열 수가 다릅니다: {source.path}")
    return rows


def validate_lexicon_sources(folder: Path) -> tuple[Path, ...]:
    """manifest가 선언한 출처를 검증하고 해시에 포함할 원본 경로를 반환한다.

    선언이 없는 기존 팩은 허용한다. 새 출처 파일을 두고 선언을 빠뜨리거나,
    선언만 남긴 채 파일을 지우는 것은 거절한다. 검증 결과를 캐시하지 않는다.
    """
    try:
        return _validate(folder)
    except LexiconSourceError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError, BuildError) as exc:
        raise LexiconSourceError("확장 사전 출처를 읽거나 검증할 수 없습니다") from exc


def _validate(folder: Path) -> tuple[Path, ...]:
    manifest_path = folder / "manifest.yaml"
    if not manifest_path.is_file() and not (folder / CATALOG).exists():
        return ()  # 기존 명명 함수가 지원한 최소 사전 입력
    manifest = read_yaml(manifest_path)
    declared = manifest.get("lexicon_sources")
    if declared is None:
        if (folder / CATALOG).exists():
            raise LexiconSourceError("출처 파일을 manifest.lexicon_sources에 선언해야 합니다")
        return ()
    if declared != CATALOG:
        raise LexiconSourceError(f"lexicon_sources는 {CATALOG}여야 합니다")
    try:
        catalog = Catalog.model_validate(read_yaml(folder / CATALOG))
    except (OSError, ValidationError) as exc:
        raise LexiconSourceError("확장 사전 출처 목록의 형식이 잘못됐습니다") from exc
    if catalog.pack != manifest.get("name", folder.name):
        raise LexiconSourceError("출처 목록의 pack이 manifest와 다릅니다")
    _verified(folder, catalog.baseline)
    baseline = _words(read_yaml(_path(folder, catalog.baseline.path)), "기준 사본")
    current = _words(read_yaml(folder / "words.yaml"), "운영 사전")
    if baseline.keys() - current.keys():
        raise LexiconSourceError("기준 사본의 단어를 확장 과정에서 삭제할 수 없습니다")
    changed = {name for name, row in current.items() if row != baseline.get(name)}
    sources = {key: _rows(folder, source) for key, source in catalog.sources.items()}
    _verify_candidates(catalog, current, sources, changed)
    return tuple(
        dict.fromkeys(
            _path(folder, item.path) for item in (catalog.baseline, *catalog.sources.values())
        )
    )


def _verify_candidates(
    catalog: Catalog,
    current: dict[str, dict[str, Any]],
    sources: dict[str, list[dict[str, str]]],
    changed: set[str],
) -> None:
    seen: set[str] = set()
    included: set[str] = set()
    for candidate in catalog.candidates:
        word = _name(candidate.word)
        if word in seen:
            raise LexiconSourceError(f"NFC 중복 선정 후보: {word}")
        seen.add(word)
        if candidate.decision == "exclude":
            if word in changed:
                raise LexiconSourceError(f"제외한 후보가 운영 사전에 등록됐습니다: {word}")
            if (candidate.source is not None or candidate.row is not None) and (
                candidate.source not in sources
                or candidate.row is None
                or candidate.row - 2 >= len(sources[candidate.source])
            ):
                raise LexiconSourceError(f"제외 후보의 출처 행이 없습니다: {word}")
            continue
        _validate_candidate(candidate, current, sources, catalog)
        included.add(word)
    if included != changed:
        raise LexiconSourceError(
            f"추가·변경 단어의 출처 누락 또는 불필요한 선정: {sorted(included ^ changed)}"
        )


def _validate_candidate(
    candidate: Candidate,
    current: dict[str, dict[str, Any]],
    sources: dict[str, list[dict[str, str]]],
    catalog: Catalog,
) -> None:
    word = _name(candidate.word)
    if candidate.source not in sources or candidate.row is None or not candidate.definition_basis:
        raise LexiconSourceError(f"선정한 단어의 출처·행·의미 근거가 없습니다: {word}")
    rows = sources[candidate.source]
    if candidate.row - 2 >= len(rows) or word not in current:
        raise LexiconSourceError(f"출처 행 또는 운영 단어가 없습니다: {word}")
    row, spec = rows[candidate.row - 2], catalog.sources[candidate.source]
    actual = current[word]
    for field, column in (
        ("word", spec.word_column),
        ("english", spec.english_column),
        ("abbreviation", spec.abbreviation_column),
    ):
        value = actual.get(field)
        if not isinstance(value, str) or _name(value).casefold() != _name(row[column]).casefold():
            raise LexiconSourceError(f"원본 {field}와 운영 사전이 다릅니다: {word}")
    if actual.get("synonyms") or actual.get("forbidden_synonyms"):
        raise LexiconSourceError(f"출처 확장으로 자유 동의어·금칙어를 활성화할 수 없습니다: {word}")
    if actual.get("is_classifier") is not False or actual.get("domain_group") is not None:
        raise LexiconSourceError(f"출처 확장으로 새 분류어·타입 정책을 만들 수 없습니다: {word}")


def source_fingerprint(folder: Path) -> str:
    """검증된 원본을 묶는다. 출처가 없는 기존 팩은 빈 문자열로 이전 해시를 보존한다."""
    paths = validate_lexicon_sources(folder)
    if not paths:
        return ""
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(folder.resolve()).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()
