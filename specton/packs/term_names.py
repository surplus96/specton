"""한 팩 안에서 NFC로 같아지는 용어 이름을 찾는다 (#264).

팩 빌드(`build.py`)와 팩 로더(`loader.py`)가 같은 기준으로 거절하도록 이 순수 함수를 함께 쓴다.
빌드는 `BuildError`, 로더는 `PackError`로 감싼다. 그래서 다른 specton 모듈을 import하지 않는다.

비교 키는 앞뒤 공백을 뺀 뒤 NFC로 맞춘 이름이다. 로더 모델은 `str_strip_whitespace=True`라
`' 창고'`를 `'창고'`로 읽으므로, 빌드도 같은 키로 봐야 빌드·로더 판정이 갈리지 않는다.
원본 문자열은 바꾸지 않는다. 키는 비교에만 쓴다.
"""

from collections.abc import Iterable
from unicodedata import normalize


def term_name_conflicts(terms: Iterable[tuple[str, Iterable[str]]]) -> list[str]:
    """`(정식 용어 이름, 동의어들)` 목록에서 이름 충돌을 모두 찾아 입력 순서대로 돌려준다.

    - 정식 용어 이름끼리 키가 같으면 충돌이다. 내용(구성·도메인)이 같아도 거절한다.
    - 동의어가 *다른* 정식 용어 이름과 키가 같으면 충돌이다. 자기 이름과 같은 동의어는 괜찮다.
    - 여러 용어가 같은 동의어를 함께 쓰는 것은 여기서 보지 않는다 (기존 모호성 처리).

    빈 목록이면 통과다. 순번은 1부터 센 입력 위치다.
    """
    entries = [(term, tuple(synonyms)) for term, synonyms in terms]
    by_key: dict[str, list[tuple[int, str]]] = {}
    for number, (term, _) in enumerate(entries, start=1):
        by_key.setdefault(_key(term), []).append((number, term))

    problems: list[str] = []
    for key, named in by_key.items():
        if len(named) > 1:
            where = ", ".join(f"{number}번째 {term!r}" for number, term in named)
            cause = _cause([term for _, term in named]) or "완전히 같은 문자열이 반복됩니다"
            problems.append(f"용어 이름 중복 {key!r} ({where}): {cause}")

    for number, (term, synonyms) in enumerate(entries, start=1):
        own = _key(term)
        for synonym in synonyms:
            key = _key(synonym)
            if not key or key == own or key not in by_key:
                continue
            other_number, other = by_key[key][0]
            cause = _cause([synonym, other])
            problems.append(
                f"{number}번째 용어 {term!r}의 동의어 {synonym!r}가 "
                f"다른 정식 용어 {other!r}({other_number}번째)와 같습니다"
                + (f": {cause}" if cause else "")
            )
    return problems


def _key(name: str) -> str:
    return normalize("NFC", name.strip())


def _cause(names: list[str]) -> str:
    """키가 같은 원본들이 왜 다른지 안내한다. 완전히 같으면 빈 문자열이다."""
    distinct = set(names)
    if len(distinct) == 1:
        return ""
    # NFC로 맞춰도 다르면 공백 차이, 공백을 빼도 다르면 조합 방식 차이다.
    spacing = len({normalize("NFC", name) for name in distinct}) > 1
    composed = len({name.strip() for name in distinct}) > 1
    # 세 번 이상 나오면 완전히 같은 문자열 반복이 다른 차이와 함께 있을 수 있다 (창고·창고·NFD).
    repeated = len(names) > len(distinct)
    if repeated:
        differences = "·".join(
            label
            for label, found in (("앞뒤 공백", spacing), ("한글 조합 방식(NFC·NFD)", composed))
            if found
        )
        return f"완전히 같은 문자열 반복과 {differences} 차이가 함께 있습니다"
    if spacing and composed:
        return "앞뒤 공백과 한글 조합 방식(NFC·NFD)이 다른 같은 이름입니다"
    if spacing:
        return "앞뒤 공백만 다른 같은 이름입니다"
    return "한글 조합 방식(NFC·NFD)만 다른 같은 이름입니다"
