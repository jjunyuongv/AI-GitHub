"""users / logins 쿼리.

**"세션"이라는 낱말을 쓰지 않는다.** 이 저장소에서 세션은 이미 대화 한 건
(`chat_sessions`)이고, 여기 있는 것은 로그인이다. 두 개념이 같은 낱말이 되면
주석마다 어느 쪽인지 되물어야 한다 — 그래서 표 이름도 `logins` 다.
"""

from app.db.pool import cursor


def upsert(github_user_id: int, login: str, avatar_url: str | None) -> int:
    """GitHub 사용자를 우리 쪽 id 로. 처음이면 만들고, 있으면 표시용 값을 갱신한다.

    **키는 `github_user_id` 다.** `login`(계정 이름)은 사용자가 언제든 바꿀 수 있어서
    그것을 키로 삼으면 개명 한 번에 남남이 되고, 그 사람의 대화가 전부 남의 것이 된다.
    이름과 아바타는 표시용이라 로그인할 때마다 최신값으로 덮는다.
    """
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (github_user_id, login, avatar_url)
                 VALUES (%s, %s, %s)
            ON CONFLICT (github_user_id) DO UPDATE
                    SET login = EXCLUDED.login,
                        avatar_url = EXCLUDED.avatar_url,
                        last_seen_at = now()
              RETURNING id
            """,
            (github_user_id, login, avatar_url),
        )
        return cur.fetchone()["id"]


def create_login(user_id: int, days: int) -> str:
    """로그인 한 건. 돌려주는 id 가 곧 쿠키에 담길 값이다."""
    with cursor() as cur:
        cur.execute(
            """INSERT INTO logins (user_id, expires_at)
               VALUES (%s, now() + make_interval(days => %s))
               RETURNING id""",
            (user_id, days),
        )
        return str(cur.fetchone()["id"])


def get_login(login_id: str) -> dict | None:
    """쿠키가 가리키는 사용자. 없거나 **만료됐으면 None**.

    **만료를 SQL 에서 본다.** 파이썬으로 가져와 비교하면 서버 타임존과 DB 타임존이
    갈릴 때 조용히 어긋난다 — `expires_at` 은 `now()` 로 만들었으므로 같은 시계로
    비교하는 것이 맞다.
    """
    with cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT u.id, u.github_user_id, u.login, u.avatar_url
              FROM logins l
              JOIN users u ON u.id = l.user_id
             WHERE l.id = %s AND l.expires_at > now()
            """,
            (login_id,),
        )
        return cur.fetchone()


def delete_login(login_id: str) -> None:
    """로그아웃. **행을 지운다** — 그래서 로그아웃이 즉시 유효하다.

    서명 토큰(JWT)이었다면 만료까지 계속 유효했을 것이고, 그것이 DB 세션을 고른 이유다.
    """
    with cursor() as cur:
        cur.execute("DELETE FROM logins WHERE id = %s", (login_id,))


def delete_expired() -> int:
    """만료된 로그인 행 정리. 남아 있어도 `get_login` 이 안 주지만 쌓일 이유는 없다."""
    with cursor() as cur:
        cur.execute("DELETE FROM logins WHERE expires_at <= now()")
        return cur.rowcount
