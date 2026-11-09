"""공식 이음동의어·금칙어를 팩 낱말로 선택한 예외를 명시적으로 검증한다 (#11)."""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from unicodedata import normalize

from specton.packs.build import BuildError, read_yaml


class SelectionError(BuildError):
    """선별 적용 기록이 실제 공식 단어 관계와 맞지 않는다."""


def validate_selection(
    folder: Path,
    official: Iterable[Mapping[str, Any]],
    *,
    registered_words: Iterable[str] | None = None,
) -> None:
    rows = tuple(official)
    canonical = {_name(w["word"]) for w in rows}
    aliases: dict[str, set[str]] = {}
    for row in rows:
        for alias in (*row["synonyms"], *row["forbidden_synonyms"]):
            aliases.setdefault(_name(alias), set()).add(_name(row["word"]))
    if registered_words is None:
        registered_words = (w["word"] for w in read_yaml(folder / "words.yaml").get("words", []))
    registered = {_name(word) for word in registered_words}
    required = (registered - canonical) & aliases.keys()
    path = folder / "standard_selection.yaml"
    data = read_yaml(path) if path.is_file() else {"exceptions": []}
    if set(data) != {"exceptions"} or not isinstance(data["exceptions"], list):
        raise SelectionError(f"{path}: exceptions 목록이 필요합니다")
    entries = data["exceptions"]
    selected: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"word", "standard_word", "reason"}:
            raise SelectionError(f"{path}: 선별 적용에는 word·standard_word·reason만 필요합니다")
        word, target, reason = (entry[k] for k in ("word", "standard_word", "reason"))
        if not all(isinstance(value, str) and value.strip() for value in (word, target, reason)):
            raise SelectionError(f"{path}: 선별 적용 값·사유는 비어 있을 수 없습니다")
        word, target = _name(word), _name(target)
        if word in selected or word not in required or target not in aliases.get(word, set()):
            raise SelectionError(
                f"{path}: 중복·불필요하거나 공식 표준어와 맞지 않는 선별 적용 {word}"
            )
        selected.add(word)
    if missing := required - selected:
        raise SelectionError(
            f"{folder}: 선별 적용 목록에 없는 공식 이음동의어·금칙어 {sorted(missing)}"
        )


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SelectionError("선별 적용 검사: 낱말·표준어는 비어 있지 않은 문자열이어야 합니다")
    return normalize("NFC", value.strip())
