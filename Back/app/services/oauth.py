"""GitHub OAuth — 인가 URL 만들기, 코드 교환, 신원 조회.

**여기서 하는 것은 신원 확인뿐이다.** 받은 액세스 토큰은 `GET /user` 한 번에 쓰고
**버린다. 어디에도 저장하지 않는다.** 저장소는 지금까지처럼 서버의 `GITHUB_TOKEN`
으로 읽는다.

왜 안 저장하는가: 배경 색인(`services/indexer.run_build`)이 요청이 끝난 뒤 큐 워커
스레드에서 GitHub 을 **다시** 부른다. 사용자 토큰으로 저장소를 읽으려면 그 시점에도
토큰이 있어야 하므로 **보관 말고는 길이 없고**, 보관하는 순간 비밀값이 둘 늘고
(토큰들 + 암호화 키) private 저장소 코드가 `snapshot_source_files` 에 평문으로
쌓이기 시작한다. 이번 범위는 로그인까지다.

그래서 **scope 를 아예 요청하지 않는다.** 스코프 없는 토큰으로도 `GET /user` 가
공개 프로필(id·login·avatar_url)을 준다. 인가 화면에는 "public data only" 로 뜬다.
"""

import logging
import secrets

import httpx

from app.config import (
    FRONTEND_ORIGIN,
    GITHUB_OAUTH_CLIENT_ID,
    GITHUB_OAUTH_CLIENT_SECRET,
)

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"

# 콜백 경로. **환경변수로 두지 않는다** — GitHub 에 등록한 값과 우리가 보내는 값이
# 반드시 같아야 하는데, 따로 적을 수 있게 하면 두 곳이 갈릴 자리가 하나 더 생긴다.
# 출처는 `FRONTEND_ORIGIN` 이다(배포에서는 `PUBLIC_ORIGIN` 이 그리로 들어간다).
CALLBACK_PATH = "/auth/callback"

TIMEOUT_SECONDS = 10.0


class OAuthError(Exception):
    """인가 흐름이 실패했다. status_code 를 API 계층이 그대로 쓴다."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def enabled() -> bool:
    """로그인 기능이 켜져 있는가. **비면 꺼진 것이다.**

    `allowlist.enabled()` 와 같은 관용구다 — 끄는 스위치를 따로 만들지 않는다.
    둘이 되면 어느 쪽이 이기는지를 또 기억해야 한다.

    **client secret 은 보지 않는다.** 켜고 끄는 판정이 두 값에 걸리면 한쪽만 채운
    상태가 "반쯤 켜짐"이 되는데, 그런 상태는 화면에는 로그인 버튼이 뜨고 누르면
    실패하는 모양이 된다. id 하나로 가르고, secret 이 비었으면 교환 단계에서 명확히
    실패시킨다.
    """
    return bool(GITHUB_OAUTH_CLIENT_ID)


def callback_url() -> str:
    return f"{FRONTEND_ORIGIN.rstrip('/')}{CALLBACK_PATH}"


def new_state() -> str:
    """CSRF 방지용 난수. 이 값이 쿠키와 조회 문자열 양쪽에 실린다."""
    return secrets.token_urlsafe(32)


def authorize_url(state: str) -> str:
    """사용자를 보낼 GitHub 인가 주소.

    **`scope` 를 넣지 않는다** — 모듈 docstring 참고. `redirect_uri` 는 등록값과
    host·port 가 정확히 일치해야 한다.
    """
    params = httpx.QueryParams(
        client_id=GITHUB_OAUTH_CLIENT_ID,
        redirect_uri=callback_url(),
        state=state,
    )
    return f"{AUTHORIZE_URL}?{params}"


def exchange_code(code: str) -> str:
    """인가 코드를 액세스 토큰으로.

    **`Accept: application/json` 을 반드시 보낸다.** 안 보내면 GitHub 이 폼 인코딩
    문자열로 답하고, `.json()` 이 거기서 깨진다.

    **GitHub 은 실패도 200 으로 답한다.** 본문에 `error` 가 실려 오므로 상태 코드만
    보면 빈 토큰을 들고 다음 단계로 간다.
    """
    if not GITHUB_OAUTH_CLIENT_SECRET:
        raise OAuthError(
            "로그인 설정이 반쪽입니다 (client secret 이 없습니다).", status_code=503
        )
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            res = client.post(
                TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": GITHUB_OAUTH_CLIENT_ID,
                    "client_secret": GITHUB_OAUTH_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": callback_url(),
                },
            )
            res.raise_for_status()
            body = res.json()
    except httpx.HTTPError as e:
        raise OAuthError(f"GitHub 인증 서버에 닿지 못했습니다: {e}")

    if body.get("error"):
        # error_description 을 그대로 노출하지 않는다 — 남의 서버가 쓴 문장이다.
        logger.warning("OAuth 코드 교환 실패: %s", body.get("error"))
        raise OAuthError("로그인에 실패했습니다. 다시 시도해 주세요.", status_code=400)

    token = body.get("access_token") or ""
    if not token:
        raise OAuthError("로그인에 실패했습니다. 다시 시도해 주세요.", status_code=400)
    return token


def fetch_user(token: str) -> dict:
    """토큰의 주인. `{github_user_id, login, avatar_url}` 만 뽑아 돌려준다.

    **토큰은 여기서 끝난다.** 호출부로 돌려주지 않으므로 저장할 방법 자체가 없다.
    """
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            res = client.get(
                USER_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                },
            )
            res.raise_for_status()
            body = res.json()
    except httpx.HTTPError as e:
        raise OAuthError(f"GitHub 사용자 정보를 읽지 못했습니다: {e}")

    if not body.get("id") or not body.get("login"):
        raise OAuthError("GitHub 사용자 정보가 비어 있습니다.")
    return {
        "github_user_id": int(body["id"]),
        "login": str(body["login"]),
        "avatar_url": body.get("avatar_url"),
    }
