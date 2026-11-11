"""A08 탐색 사전의 오프라인 사본·출처·승인 검증. 운영 팩은 변경하지 않는다."""

import hashlib
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from specton.codegen.model import Normalized
from specton.codegen.naming import PackLexicon, load_naming_rules, load_pack_lexicon, physical_name
from specton.codegen.normalize import PackRef, normalize
from specton.contracts import DesignState
from specton.packs.build import BuildError, pack_content_hash, read_lock_versions, read_yaml
from specton.packs.lexicon_sources import Source, validate_lexicon_sources, verified_source_rows
from specton.packs.loader import Pack, PackError, PackName, Version, Word, load_pack
from specton.packs.provenance import policy_digest

Text = Annotated[str, StringConstraints(min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*$")]


class Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Addition(Strict):
    word: Word
    source: Identifier
    row: int = Field(ge=2)
    selection_reason: Text
    definition_basis: Text


class OverlaySpec(Strict):
    schema_version: Literal[1]
    scope: Literal["evaluation_exploration"]
    condition_id: Identifier
    dictionary_version: Text
    pack: PackName
    base_pack_version: Version
    base_common_version: Version
    base_policy_digest: Sha256
    sources: dict[Identifier, Source] = Field(min_length=1)
    additions: tuple[Addition, ...] = Field(min_length=1)


class Review(Strict):
    role: Literal["R1", "R4"]
    reviewer: Text
    decision: Literal["approved"]
    reference: Text


class R1ScopedOverride(Strict):
    """R4 확인을 받은 것으로 기록하지 않는, 선정 해시 한 건의 명시적 R1 결정."""

    subject_sha256: Sha256
    authorized_role: Literal["R1"]
    authorized_by: Text
    replaces_role: Literal["R4"]
    scope: Literal["this_selection_only"]
    reason: Text
    directive_reference: Text


class Reviews(Strict):
    subject_sha256: Sha256
    reviews: tuple[Review, ...]
    approval_mode: Literal["r1_r4", "r1_scoped_override"] = "r1_r4"
    r1_override: R1ScopedOverride | None = None


class Manifest(Strict):
    spec: OverlaySpec
    subject_sha256: Sha256


def _digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def _name(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip())


def _base(root: Path, spec: OverlaySpec) -> Pack:
    pack = load_pack(spec.pack, root=root)
    if pack.manifest.status != "approved" or pack.common.manifest.status != "approved":
        raise ValueError("탐색 사전의 기준 팩·공통 팩이 승인되지 않았습니다")
    if (pack.manifest.version, pack.common.manifest.version) != (
        spec.base_pack_version,
        spec.base_common_version,
    ):
        raise ValueError("기준 팩 버전이 선정 기록과 다릅니다")
    for manifest in (pack.manifest, pack.common.manifest):
        folder = root / manifest.name
        if read_lock_versions(folder).get(manifest.version) != pack_content_hash(folder):
            raise ValueError("기준 팩 내용이 pack.lock과 다릅니다")
    if policy_digest(root, spec.pack) != spec.base_policy_digest:
        raise ValueError("기준 policy_digest가 선정 기록과 다릅니다")
    return pack


def _lexicon(root: Path, folder: Path, spec: OverlaySpec, subject: str) -> PackLexicon:
    pack = _base(root, spec)
    base = load_pack_lexicon(spec.pack, root)
    rows = {key: verified_source_rows(folder, source) for key, source in spec.sources.items()}
    tokens = dict(base.tokens)
    abbreviations = {v.casefold() for v in tokens.values()}
    used_sources = set()
    for addition in spec.additions:
        word = addition.word
        name = _name(word.word)
        rule = pack.common.naming.abbreviation
        _check_word(word, base, tokens, abbreviations, (rule.min_length, rule.max_length))
        _verify_row(addition, spec, rows)
        used_sources.add(addition.source)
        tokens[name] = word.abbreviation
        abbreviations.add(word.abbreviation.casefold())
    if used_sources != spec.sources.keys():
        raise ValueError("선정 단어에서 사용하지 않는 출처가 있습니다")
    return PackLexicon(
        terms=MappingProxyType(dict(base.terms)),
        tokens=MappingProxyType(tokens),
        separator=base.separator,
        digest=_digest({"base": base.digest, "overlay": subject}),
    )


def _check_word(
    word: Word,
    base: PackLexicon,
    tokens: dict[str, str],
    abbreviations: set[str],
    limits: tuple[int, int],
) -> None:
    if _name(word.word) in tokens or physical_name(word.word, base) is not None:
        raise ValueError("기존에 등록·조합 가능한 이름이나 중복 단어는 확장할 수 없습니다")
    if (
        word.synonyms
        or word.forbidden_synonyms
        or word.is_classifier
        or word.domain_group is not None
    ):
        raise ValueError("탐색 사전으로 별칭·금칙어·분류어·타입 정책을 변경할 수 없습니다")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", word.abbreviation) or not (
        limits[0] <= len(word.abbreviation) <= limits[1]
    ):
        raise ValueError("약어가 기준 팩의 형식·길이에 맞지 않습니다")
    if word.abbreviation.casefold() in abbreviations:
        raise ValueError("기존 또는 새 단어와 약어가 겹칩니다")


def _verify_row(
    addition: Addition, spec: OverlaySpec, rows: dict[str, list[dict[str, str]]]
) -> None:
    if addition.source not in rows or addition.row - 2 >= len(rows[addition.source]):
        raise ValueError("추가 단어의 출처 행이 없습니다")
    source = spec.sources[addition.source]
    row = rows[addition.source][addition.row - 2]
    for actual, column in (
        (addition.word.word, source.word_column),
        (addition.word.english, source.english_column),
        (addition.word.abbreviation, source.abbreviation_column),
    ):
        if _name(actual).casefold() != _name(row[column]).casefold():
            raise ValueError("추가 단어의 한글·영문·약어가 원본 행과 다릅니다")


def _reviews(folder: Path, subject: str, *, required: bool) -> Reviews | None:
    path = folder / "reviews.json"
    if not path.exists():
        if required:
            raise ValueError("탐색 실행에는 사전의 해시에 연결된 R1·R4 승인이 필요합니다")
        return None
    record = Reviews.model_validate_json(path.read_text(encoding="utf-8"))
    if record.subject_sha256 != subject:
        raise ValueError("R1·R4 승인 대상 해시 또는 역할이 일치하지 않습니다")
    if record.approval_mode == "r1_r4":
        if record.r1_override is not None or sorted(r.role for r in record.reviews) != ["R1", "R4"]:
            raise ValueError("R1·R4 승인 대상 해시 또는 역할이 일치하지 않습니다")
    else:
        override = record.r1_override
        if (
            override is None
            or override.subject_sha256 != subject
            or len(record.reviews) != 1
            or record.reviews[0].role != "R1"
            or record.reviews[0].reviewer != override.authorized_by
            or record.reviews[0].reference != override.directive_reference
        ):
            raise ValueError(
                "R1 단독 확정은 동일 선정 해시·지시 근거·확정자와 R1 기록 하나가 필요합니다"
            )
    return record


@dataclass(frozen=True)
class LexiconOverlay:
    folder: Path
    spec: OverlaySpec
    subject_sha256: str
    lexicon: PackLexicon
    reviews: Reviews | None

    @property
    def base_root(self) -> Path:
        return self.folder / "base"

    def provenance(self) -> dict[str, str]:
        return {
            "evaluation_scope": "exploration",
            "lexicon_condition_id": self.spec.condition_id,
            "dictionary_version": self.spec.dictionary_version,
            "base_policy_digest": self.spec.base_policy_digest,
            "overlay_subject_sha256": self.subject_sha256,
            "overlay_approval_mode": self.reviews.approval_mode if self.reviews else "pending",
            "overlay_r1_override_ref": self.reviews.r1_override.directive_reference
            if self.reviews and self.reviews.r1_override
            else "",
            "overlay_review_refs": json.dumps(
                {r.role: r.reference for r in self.reviews.reviews} if self.reviews else {},
                ensure_ascii=False,
                sort_keys=True,
            ),
        }

    def normalize(self, state: DesignState) -> DesignState:
        if self.reviews is None:
            raise ValueError("승인되지 않은 탐색 사전은 실행할 수 없습니다")
        self.assert_current()
        if state.versions.pack_id != self.spec.pack or state.versions.pack_version not in (
            None,
            self.spec.base_pack_version,
        ):
            raise ValueError("설계의 팩·버전과 탐색 조건이 일치하지 않습니다")
        versioned = state.evolve(
            versions=state.versions.evolve(pack_version=self.spec.base_pack_version)
        )
        result = normalize(
            versioned,
            pack=PackRef(self.spec.pack, self.spec.base_pack_version),
            lexicon=self.lexicon,
            rules=load_naming_rules(self.base_root),
        )
        if not isinstance(result, Normalized):
            detail = ", ".join(f"{p.code.value}:{p.target}" for p in result.problems)
            raise ValueError(f"탐색 조건 정리에 실패했습니다 ({detail})")
        policy_record: dict[str, object] = {
            "scope": "evaluation_exploration",
            "base": self.spec.base_policy_digest,
            "overlay": self.subject_sha256,
            "reviews": {r.role: r.model_dump(mode="json") for r in self.reviews.reviews},
        }
        if self.reviews.r1_override is not None:
            policy_record["approval_mode"] = self.reviews.approval_mode
            policy_record["r1_override"] = self.reviews.r1_override.model_dump(mode="json")
        policy = _digest(policy_record)
        return versioned.evolve(
            normalized=result.model.evolve(
                common_version=self.spec.base_common_version,
                policy_digest=policy,
            )
        )

    def assert_current(self) -> None:
        current = load_overlay(self.folder)
        if (
            current.subject_sha256 != self.subject_sha256
            or current.spec != self.spec
            or current.lexicon != self.lexicon
            or current.reviews != self.reviews
        ):
            raise ValueError("탐색 조건이나 승인 기록이 로드 후 바뀌었습니다")


def load_overlay(folder: Path, *, require_reviews: bool = True) -> LexiconOverlay:
    """사본·CSV·기준 팩·승인을 매번 확인한다. 운영 팩으로 우회하지 않는다."""
    try:
        return _load_overlay(folder, require_reviews=require_reviews)
    except (OSError, BuildError, PackError, ValidationError) as exc:
        raise ValueError(f"탐색 사전 파일·출처·기준 팩 검증 실패: {type(exc).__name__}") from exc


def _load_overlay(folder: Path, *, require_reviews: bool) -> LexiconOverlay:
    folder = folder.resolve()
    if any((folder / name).is_symlink() for name in ("base", "overlay.json", "reviews.json")):
        raise ValueError("탐색 기준·선정·승인 사본은 symlink일 수 없습니다")
    manifest = Manifest.model_validate_json((folder / "overlay.json").read_text(encoding="utf-8"))
    spec = manifest.spec
    if _digest(spec.model_dump(mode="json")) != manifest.subject_sha256:
        raise ValueError("탐색 사전의 선정 내용 해시가 다릅니다")
    _base_files(folder / "base", spec.pack)
    lexicon = _lexicon(folder / "base", folder, spec, manifest.subject_sha256)
    return LexiconOverlay(
        folder,
        spec,
        manifest.subject_sha256,
        lexicon,
        _reviews(folder, manifest.subject_sha256, required=require_reviews),
    )


def _base_files(root: Path, pack: str) -> set[Path]:
    files: set[Path] = set()
    for name in ("common", pack):
        files.update((root / name).rglob("*.yaml"))
        files.add(root / name / "pack.lock")
        files.update(validate_lexicon_sources(root / name))
    sources = root / "sources/sources.yaml"
    if sources.exists():
        files.add(sources)
        files.update(sources.parent / s["path"] for s in read_yaml(sources)["files"].values())
    if any(p.is_symlink() or not p.resolve().is_relative_to(root) for p in files):
        raise ValueError("기준 사본의 파일 경로가 팩 루트를 벗어나거나 symlink입니다")
    return files


def compose_overlay(
    root: Path, spec_path: Path, destination: Path, *, reviews: Path | None = None
) -> LexiconOverlay:
    """새 사본만 생성한다. 승인이 없으면 준비 자료이며 평가 실행은 거절한다."""
    root = root.resolve()
    destination = destination.absolute()
    if (
        destination.resolve().is_relative_to(root)
        or destination.exists()
        or destination.is_symlink()
    ):
        raise ValueError("출력은 기준 팩 밖의 존재하지 않는 새 경로여야 합니다")
    spec = OverlaySpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
    _lexicon(root, spec_path.parent, spec, _digest(spec.model_dump(mode="json")))
    files = _base_files(root, spec.pack)
    sources = {
        key: source.model_copy(update={"path": f"sources/{key}.csv"})
        for key, source in spec.sources.items()
    }
    stored = spec.model_copy(update={"sources": sources})
    manifest = Manifest(spec=stored, subject_sha256=_digest(stored.model_dump(mode="json")))
    destination.mkdir(parents=True)
    try:
        for path in files:
            target = destination / "base" / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        for key, source in spec.sources.items():
            target = destination / sources[key].path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(spec_path.parent / source.path, target)
        (destination / "overlay.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        if reviews is not None:
            shutil.copyfile(reviews, destination / "reviews.json")
        return load_overlay(destination, require_reviews=reviews is not None)
    except Exception:
        shutil.rmtree(destination)
        raise
