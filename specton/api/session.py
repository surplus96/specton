"""세션 발급: 모든 run 접근의 소유자(`owner_ref`)를 정한다 (ADR-0011).

발급은 이 의존성 한 곳에서만 한다. 세션 값은 로그·응답 본문에 넣지 않는다.
"""

import re
import secrets
from typing import Annotated

from fastapi import Depends, Request, Response

SESSION_COOKIE = "specton_session"
# 발급 형식(token_urlsafe(32))만 받는다. 다른 값이면 새로 발급한다.
_SESSION_FORMAT = re.compile(r"[A-Za-z0-9_-]{43}")


def owner_ref(request: Request, response: Response) -> str:
    """쿠키의 세션 값을 돌려준다. 없거나 형식이 다르면 새 값을 발급해 쿠키로 보낸다.

    클라이언트마다 다른 값이어야 다른 실행 접근 차단(TC-N03)을 시험할 수 있다.
    """
    value = request.cookies.get(SESSION_COOKIE)
    if value is not None and _SESSION_FORMAT.fullmatch(value):
        return value
    value = secrets.token_urlsafe(32)
    response.set_cookie(SESSION_COOKIE, value, httponly=True, samesite="lax")
    return value


OwnerRef = Annotated[str, Depends(owner_ref)]
