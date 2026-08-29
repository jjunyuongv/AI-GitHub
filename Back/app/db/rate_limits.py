"""남용 방지 카운터의 DB 저장소.

`services/rate_limit.py` 가 DB 를 쓸 수 있을 때 여기로 내려온다.

**파일 구현과 다른 점은 원자성을 얻는 방법이다.** 파일은 프로세스 안 `threading.Lock`
으로 read-modify-write 를 직렬화하는데, 워커가 여럿이면 Lock 이 워커마다 따로라
카운트가 샌다. 여기서는:

- 일일 카운터: `INSERT … ON CONFLICT DO UPDATE … RETURNING` **한 문장**으로 증가시키고
  그 결과를 본다. 증가와 확인 사이에 다른 요청이 끼어들 틈이 없다
- IP 윈도우: 합계가 아니라 개별 시각을 세야 해서 한 문장으로 안 된다.
  `pg_advisory_xact_lock` 으로 **그 IP 에 대해서만** 직렬화한다 (다른 IP 는 안 막힌다)

상한을 넘으면 예외를 던져 트랜잭션을 통째로 되돌린다 — 거절된 요청이 카운터를
올려놓고 가면 안 된다.
"""

from app.db.pool import cursor


class _Rejected(Exception):
    """트랜잭션을 되돌리기 위한 내부 신호. 이 모듈 밖으로 나가지 않는다."""

    def __init__(self, reason: str, retry_after: int):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


def reserve(
    day: str,
    ip: str,
    *,
    call_limit: int,
    token_limit: int,
    ip_limit: int,
    window_seconds: int,
    seconds_until_tomorrow: int,
    user_id: int | None = None,
    user_limit: int = 0,
) -> dict | None:
    """이번 요청 몫을 예약한다. 통과하면 None, 막히면 {reason, retry_after}.

    상한이 0 이면 그 검사를 건너뛴다(파일 구현과 같은 규칙).

    `user_id` 는 로그인한 요청에만 있다. **None 이면 사용자 층을 건너뛰고, 그러면
    이 함수가 하는 일이 로그인 도입 전과 글자 그대로 같다** — `rate_limit_user_daily`
    에 행도 안 생긴다.
    """
    try:
        with cursor() as cur:
            if ip_limit:
                # 이 IP 에 대해서만 직렬화한다. 아래 count 와 insert 사이에 같은 IP 의
                # 다른 요청이 끼면 둘 다 통과해 상한을 넘길 수 있다.
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (ip,))

                # 윈도우 밖 기록은 이 IP 것만 지운다 — 인덱스가 있어 싸고,
                # 전체 정리는 관리자 화면이 usage() 를 부를 때 한다.
                cur.execute(
                    """DELETE FROM rate_limit_hits
                        WHERE ip = %s AND at <= now() - make_interval(secs => %s)""",
                    (ip, window_seconds),
                )
                cur.execute(
                    """SELECT count(*) AS n, min(at) AS oldest
                         FROM rate_limit_hits
                        WHERE ip = %s AND at > now() - make_interval(secs => %s)""",
                    (ip, window_seconds),
                )
                row = cur.fetchone()
                if row["n"] >= ip_limit:
                    # 가장 오래된 요청이 윈도우를 빠져나가면 한 자리가 난다.
                    cur.execute(
                        "SELECT GREATEST(1, CEIL(EXTRACT(EPOCH FROM"
                        " (%s - (now() - make_interval(secs => %s)))))) AS wait",
                        (row["oldest"], window_seconds),
                    )
                    retry_after = int(cur.fetchone()["wait"])
                    raise _Rejected(
                        f"요청이 너무 잦습니다."
                        f" {max(1, round(retry_after / 60))}분 후에 다시 시도해 주세요.",
                        retry_after,
                    )

            # 증가와 확인이 한 문장이다. 나눠 쓰면 동시 요청이 함께 상한을 넘는다.
            cur.execute(
                """INSERT INTO rate_limit_daily (day, calls) VALUES (%s, 1)
                   ON CONFLICT (day) DO UPDATE SET calls = rate_limit_daily.calls + 1
                   RETURNING calls, tokens""",
                (day,),
            )
            daily = cur.fetchone()

            # calls 는 이번 요청을 **포함한** 값이라 초과(>)로 본다.
            # tokens 는 사후 기록이라 이번 몫이 없으므로 도달(>=)로 본다.
            # (파일 구현의 "증가 전 값 >= 상한" 과 같은 경계다)
            if (call_limit and daily["calls"] > call_limit) or (
                token_limit and daily["tokens"] >= token_limit
            ):
                raise _Rejected(
                    "오늘 분석 한도를 모두 사용했습니다. 내일 다시 시도해 주세요.",
                    seconds_until_tomorrow,
                )

            # 사용자 층. **서비스 상한을 통과한 뒤에 본다** — 순서가 반대면 서비스가
            # 이미 천장에 닿았는데 사용자 카운터만 올라간다.
            #
            # 위 일일 카운터와 같은 한 문장 관용구다. 상한 판정도 같은 경계로 본다
            # (이번 요청을 포함한 값이라 초과 `>`).
            if user_id is not None and user_limit:
                cur.execute(
                    """INSERT INTO rate_limit_user_daily (day, user_id, calls)
                            VALUES (%s, %s, 1)
                       ON CONFLICT (day, user_id) DO UPDATE
                              SET calls = rate_limit_user_daily.calls + 1
                        RETURNING calls""",
                    (day, user_id),
                )
                if cur.fetchone()["calls"] > user_limit:
                    raise _Rejected(
                        "오늘 사용할 수 있는 질문 수를 다 썼습니다. 내일 다시 시도해 주세요.",
                        seconds_until_tomorrow,
                    )

            if ip_limit:
                cur.execute("INSERT INTO rate_limit_hits (ip) VALUES (%s)", (ip,))
    except _Rejected as e:
        return {"reason": e.reason, "retry_after": e.retry_after}
    return None


def add_tokens(day: str, tokens: int) -> None:
    """LLM 호출이 끝난 뒤 실제 사용량을 더한다. 증가는 한 문장이라 원자적이다."""
    with cursor() as cur:
        cur.execute(
            """INSERT INTO rate_limit_daily (day, tokens) VALUES (%s, %s)
               ON CONFLICT (day) DO UPDATE
                  SET tokens = rate_limit_daily.tokens + EXCLUDED.tokens""",
            (day, tokens),
        )


def usage(day: str, window_seconds: int) -> dict:
    """오늘 카운터와 지금 추적 중인 IP 수.

    윈도우를 벗어난 기록을 여기서 **전부** 지운다 — 다시 오지 않는 IP 의 행은
    reserve() 가 치우지 못하고 남는다. 관리자 화면 조회는 드물어 부담이 없다.
    """
    with cursor() as cur:
        cur.execute(
            "DELETE FROM rate_limit_hits WHERE at <= now() - make_interval(secs => %s)",
            (window_seconds,),
        )
        cur.execute(
            "SELECT calls, tokens FROM rate_limit_daily WHERE day = %s", (day,)
        )
        row = cur.fetchone() or {"calls": 0, "tokens": 0}
        cur.execute("SELECT count(DISTINCT ip) AS n FROM rate_limit_hits")
        tracked = cur.fetchone()["n"]

    return {"calls": row["calls"], "tokens": row["tokens"], "tracked_ips": tracked}
