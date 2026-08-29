"""로그인 쿠키를 읽고 쓴다. "지금 요청은 누구인가"의 유일한 답이다.

**대화 세션(`chat_sessions`)과 다른 것이다.** 이름을 그렇게 나눈 이유는
`app/db/users.py` 의 머리말에 있다.

## 쿠키에 무엇을 담는가

`logins.id`(UUID) 하나다. 서명도 암호화도 하지 않는다 — **값 자체가 아무것도 뜻하지
않고**, 서버가 DB 를 봐야만 주인을 알 수 있기 때문이다. 그래서 로그아웃이 즉시
유효하고(행을 지운다) 비밀키가 하나도 늘지 않는다.

## 실패하면 익명으로 떨어진다

DB 를 못 읽으면 `None` 을 준다. 그러면 그 요청은 익명으로 취급되고, 자기 대화에는
접근하지 못한다(404). **막는 쪽으로 틀리는 것이 맞다** — 반대로 틀리면 남의 대화가
열린다.
"""

import logging

from app import config
from app.db import users
from app.db.pool import DB_ERRORS

logger = logging.getLogger(__name__)

# 로그인 쿠키. 이름에 접두어를 두는 것은 같은 호스트의 다른 앱과 섞이지 않게 하기
# 위해서다 — 로컬 개발에서 localhost 는 포트가 달라도 같은 쿠키 공간이다.
COOKIE_NAME = "repodive_login"

# 인가 흐름 동안만 사는 CSRF 쿠키. 콜백에서 조회 문자열의 state 와 대조한다.
STATE_COOKIE_NAME = "repodive_oauth_state"

# state 쿠키 수명(초). 사람이 GitHub 인가 화면을 보고 누르는 시간이면 충분하다.
STATE_MAX_AGE_SECONDS = 600


def _cookie_kwargs() -> dict:
    """모든 쿠키에 공통으로 붙는 속성.

    - **HttpOnly**: 자바스크립트가 못 읽는다. 화면이 LLM 답변을 마크다운으로 렌더하므로
      스크립트가 읽을 수 있는 자리에 두면 안 된다
    - **SameSite=Lax**: 남의 사이트에서 온 POST 에는 안 실린다. 그러면서 GitHub 에서
      돌아오는 **최상위 GET 이동**에는 실려서 콜백이 성립한다 (Strict 면 그 이동에도
      안 실려 state 대조가 통째로 깨진다)
    - **Secure**: `config.COOKIE_SECURE` 가 정한다. 비워 두면 `FRONTEND_ORIGIN` 이
      https 인지로 유도된다
    - **path=/**: `/auth` 와 `/chat` 이 같은 쿠키를 봐야 한다
    """
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": config.COOKIE_SECURE,
        "path": "/",
    }


def set_login_cookie(response, login_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        login_id,
        max_age=config.LOGIN_SESSION_DAYS * 24 * 3600,
        **_cookie_kwargs(),
    )


def clear_login_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, **_cookie_kwargs())


def set_state_cookie(response, state: str) -> None:
    response.set_cookie(
        STATE_COOKIE_NAME, state, max_age=STATE_MAX_AGE_SECONDS, **_cookie_kwargs()
    )


def clear_state_cookie(response) -> None:
    response.delete_cookie(STATE_COOKIE_NAME, **_cookie_kwargs())


def current_user(request) -> dict | None:
    """이 요청의 사용자. 로그인이 꺼져 있거나 쿠키가 없거나 만료면 None.

    **로그인이 꺼져 있으면 쿠키를 아예 보지 않는다.** 그래야 껐을 때의 동작이 로그인
    도입 전과 정확히 같아진다 — 옛 쿠키가 브라우저에 남아 있어도 아무 영향이 없다.
    """
    from app.services import oauth

    if not oauth.enabled():
        return None
    login_id = request.cookies.get(COOKIE_NAME)
    if not login_id:
        return None
    try:
        return users.get_login(login_id)
    except DB_ERRORS as e:
        # 값이 아니라 사실만 남긴다. 쿠키 값은 로그에 쓰지 않는다.
        logger.warning("로그인을 확인하지 못해 익명으로 처리합니다: %s", e)
        return None
    except ValueError:
        # UUID 가 아닌 쿠키. 손으로 만들었거나 옛 형식이다.
        return None


def current_user_id(request) -> int | None:
    user = current_user(request)
    return user["id"] if user else None
