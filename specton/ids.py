"""설계 객체의 내부 ID 계산 (ADR-0016). A03 노드와 모델 정리(`codegen/`)가 함께 쓴다.

같은 입력이면 실행이 달라도 같은 ID가 나온다. 이 모듈은 다른 specton 모듈을 import하지 않아
`nodes/`와 `codegen/` 어느 쪽에서 가져다 써도 의존 방향 규칙(`codegen/`은 노드·LLM client를
import하지 않음)을 지킨다.
"""

import hashlib
import unicodedata

ID_HEX_LENGTH = 16  # ID 접두어 뒤에 붙는 해시 글자 수


def stable_id(prefix: str, *parts: str) -> str:
    """`prefix`와 `parts`로 만든 ID. 한글 조합 방식 차이(NFC·NFD)는 NFC로 맞춘다.

    조각은 단위 구분 문자(U+001F)로 이어 붙여, 조각 경계가 다르면 다른 ID가 된다.
    """
    key = "\x1f".join(unicodedata.normalize("NFC", p) for p in parts)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:ID_HEX_LENGTH]
    return f"{prefix}-{digest}"
