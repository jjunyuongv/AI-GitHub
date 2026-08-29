"""남용 방지. 세 층이다 — 서비스 전체 하루 상한 · IP별 짧은 구간 제한 · 사용자별 하루 상한.

**서비스 전체 상한은 로그인이 생겨도 합산으로 남는다.** 그것은 공평성 장치가 아니라
**비용 천장**이라 사용자 수와 무관해야 한다. 사용자별 층(`USER_DAILY_LIMIT`)은 그 아래
따로 놓여, 한 사람이 천장을 혼자 다 쓰는 것을 막는다.

**익명 요청은 사용자 층을 지나지 않는다**(`user_id` 가 None). 그래서 로그인이 꺼져
있거나 로그인하지 않은 방문자의 동작은 로그인 도입 전과 **완전히 같다** —
`tests/test_rate_limit.py` 와 `tests/test_db_rate_limits.py` 가 그것을 고정한다.

**캐시 히트에는 두 제한 모두 걸지 않는다.** LLM 비용이 들지 않는 요청까지 막을 이유가 없어서
호출부가 캐시를 조회한 뒤, 미스일 때만 check_and_reserve()를 부른다.

토큰 상한은 사후 판정이다. 호출 전에는 그 요청이 쓸 토큰을 알 수 없으므로
'누적이 상한을 넘으면 다음 요청부터 차단'이 되고, 상한을 넘기는 마지막 한 번은 통과한다.

**저장은 DB 를 우선하고, DATABASE_URL 이 없으면 파일로 폴백한다.**

DB 를 먼저 쓰는 이유는 다중 워커다. 파일 경로는 프로세스 안 Lock 으로 read-modify-write 를
직렬화하는데, `uvicorn --workers 2` 이상이면 워커마다 Lock 이 따로라 상한이 워커 수만큼
느슨해진다. DB 경로는 Lock 이 아니라 SQL 한 문장의 원자성으로 푼다(db/rate_limits.py).

그렇다고 DB 를 **요구하지는 않는다.** DB 가 없다고 남용 방지가 통째로 꺼지면
안전장치를 없애는 셈이라, 그때는 지금까지의 파일 경로가 그대로 동작한다.
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from app.config import (
    DAILY_LLM_CALL_LIMIT,
    DAILY_TOKEN_LIMIT,
    IP_RATE_LIMIT,
    IP_RATE_WINDOW_SECONDS,
    TRUST_PROXY_HEADERS,
    USER_DAILY_LIMIT,
)
from app.db import pool
from app.db import rate_limits as store
from app.db.pool import DB_ERRORS

STATE_PATH = Path(__file__).resolve().parents[2] / "cache" / "rate_limit.json"

logger = logging.getLogger(__name__)

# **파일 경로 전용 Lock 이다.** 단일 프로세스 안에서만 유효하므로 워커가 여럿이면
# 어긋난다 — 그래서 DB 를 쓸 수 있으면 그쪽(SQL 원자성)으로 간다.
_lock = threading.Lock()


def _use_db() -> bool:
    return pool.is_enabled()


class RateLimitExceeded(Exception):
    """상한 초과. status_code와 retry_after를 API 계층이 그대로 응답에 쓴다."""

    def __init__(self, message: str, retry_after: int, status_code: int = 429):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after  # 초. Retry-After 헤더로 나간다


def client_ip(request) -> str:
    """실제 클라이언트 IP.

    X-Forwarded-For는 클라이언트가 마음대로 넣을 수 있어서, 프록시 뒤에 있다고
    설정했을 때만(TRUST_PROXY_HEADERS) 신뢰한다. 아니면 TCP 연결 IP를 쓴다.
    """
    if TRUST_PROXY_HEADERS:
        # 맨 앞이 원 클라이언트, 뒤는 거쳐온 프록시들이다.
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip():
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip", "")
        if real_ip.strip():
            return real_ip.strip()
    return request.client.host if request.client else "unknown"


# ── 저장소 접근 (PostgreSQL로 옮길 때 이 둘만 교체) ──────────

def _read_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("사용량 상태를 읽지 못했습니다 (%s): %s", STATE_PATH, e)
        return {}


def _write_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        logger.warning("사용량 상태를 쓰지 못했습니다 (%s): %s", STATE_PATH, e)


# ── 상태 정리 ────────────────────────────────────────────────

def _today() -> str:
    """usage 페이지 집계와 같은 로컬 타임존 기준."""
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _seconds_until_tomorrow() -> int:
    """일일 카운터가 리셋되는 자정까지 남은 초."""
    now = datetime.now().astimezone()
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((midnight - now).total_seconds()))


def _normalize(state: dict, now: float) -> dict:
    """날짜가 바뀌었으면 일일 카운터를 리셋하고, 윈도우 밖 IP 기록을 버린다."""
    today = _today()
    if state.get("date") != today:
        state = {"date": today, "calls": 0, "tokens": 0, "ips": state.get("ips", {})}

    # IP 윈도우는 시간 기준이라 날짜 경계와 무관하게 따로 정리한다.
    # 자정에 같이 비우면 그 순간 IP 제한이 풀려 우회 구멍이 된다.
    pruned = {}
    for addr, hits in state.get("ips", {}).items():
        recent = [t for t in hits if now - t < IP_RATE_WINDOW_SECONDS]
        if recent:
            pruned[addr] = recent
    state["ips"] = pruned
    return state


# ── 제한 ────────────────────────────────────────────────────

def check_and_reserve(ip: str, user_id: int | None = None) -> None:
    """제한을 검사하고 이번 요청 몫을 카운트에 반영한다.

    호출 전에 미리 세어 둬야 동시 요청이 함께 상한을 넘기지 못한다.
    LLM 호출이 실패해도 이 몫은 되돌리지 않는다 (남는 쪽보다 덜 쓰는 쪽이 안전).

    `user_id` 는 로그인한 요청에만 있다. **None 이면 사용자 층을 아예 건너뛴다.**

    **파일 폴백 경로는 `user_id` 를 무시한다.** 로그인은 DB 가 있어야 성립하므로
    (`logins` 표가 거기 있다) 파일 경로에 로그인한 요청이 도달할 수 없다. 쓰지 않는
    분기를 만들어 두면 나중에 왜 있는지 모르게 된다.
    """
    if _use_db():
        try:
            rejected = store.reserve(
                _today(),
                ip,
                user_id=user_id,
                user_limit=USER_DAILY_LIMIT,
                call_limit=DAILY_LLM_CALL_LIMIT,
                token_limit=DAILY_TOKEN_LIMIT,
                ip_limit=IP_RATE_LIMIT,
                window_seconds=IP_RATE_WINDOW_SECONDS,
                seconds_until_tomorrow=_seconds_until_tomorrow(),
            )
        except DB_ERRORS as e:
            # **막지 않고 통과시킨다.** 상한은 비용을 지키는 장치이지 서비스의 관문이 아니다.
            # DB 장애로 모든 분석이 429 가 되면 장애가 두 배로 커진다.
            logger.warning("남용 방지 카운터를 쓰지 못해 이번 요청은 통과시킵니다: %s", e)
            return
        if rejected:
            raise RateLimitExceeded(rejected["reason"], rejected["retry_after"])
        return

    now = time.time()
    with _lock:
        state = _normalize(_read_state(), now)

        hits = state["ips"].get(ip, [])
        if IP_RATE_LIMIT and len(hits) >= IP_RATE_LIMIT:
            # 가장 오래된 요청이 윈도우를 빠져나가면 한 자리가 난다.
            retry_after = max(1, int(IP_RATE_WINDOW_SECONDS - (now - hits[0])))
            raise RateLimitExceeded(
                f"요청이 너무 잦습니다. {max(1, round(retry_after / 60))}분 후에 다시 시도해 주세요.",
                retry_after,
            )

        exhausted = (DAILY_LLM_CALL_LIMIT and state["calls"] >= DAILY_LLM_CALL_LIMIT) or (
            DAILY_TOKEN_LIMIT and state["tokens"] >= DAILY_TOKEN_LIMIT
        )
        if exhausted:
            raise RateLimitExceeded(
                "오늘 분석 한도를 모두 사용했습니다. 내일 다시 시도해 주세요.",
                _seconds_until_tomorrow(),
            )

        state["ips"][ip] = hits + [now]
        state["calls"] += 1
        _write_state(state)


def record_tokens(tokens: int) -> None:
    """LLM 호출이 끝난 뒤 실제 사용 토큰을 더한다."""
    if _use_db():
        try:
            store.add_tokens(_today(), tokens)
        except DB_ERRORS as e:
            # 기록에 실패해도 응답은 이미 나갔다. 경고만 남긴다(run_log 와 같은 방침).
            logger.warning("사용 토큰을 기록하지 못했습니다: %s", e)
        return

    with _lock:
        state = _normalize(_read_state(), time.time())
        state["tokens"] += tokens
        _write_state(state)


def today_usage() -> dict:
    """오늘 사용량과 상한. 상한이 0이면 그 제한은 꺼진 상태다."""
    today, counts = _today(), None
    if _use_db():
        try:
            counts = store.usage(today, IP_RATE_WINDOW_SECONDS)
        except DB_ERRORS as e:
            # 관리자 화면이 0 을 보여주면 "안 쓰고 있다"로 오해한다. 그보다는 비는 편이 낫지만,
            # 여기서 예외를 올리면 /admin/usage 전체가 죽는다 — 0 으로 두고 경고를 남긴다.
            logger.warning("오늘 사용량을 읽지 못했습니다: %s", e)
            counts = {"calls": 0, "tokens": 0, "tracked_ips": 0}

    if counts is None:
        with _lock:
            state = _normalize(_read_state(), time.time())
        today = state["date"]
        counts = {
            "calls": state["calls"],
            "tokens": state["tokens"],
            "tracked_ips": len(state["ips"]),
        }

    def _pct(used: int, limit: int) -> float | None:
        return round(used / limit * 100, 1) if limit else None

    return {
        "date": today,
        "calls": counts["calls"],
        "call_limit": DAILY_LLM_CALL_LIMIT,
        "calls_pct": _pct(counts["calls"], DAILY_LLM_CALL_LIMIT),
        "tokens": counts["tokens"],
        "token_limit": DAILY_TOKEN_LIMIT,
        "tokens_pct": _pct(counts["tokens"], DAILY_TOKEN_LIMIT),
        "ip_limit": IP_RATE_LIMIT,
        "ip_window_seconds": IP_RATE_WINDOW_SECONDS,
        "tracked_ips": counts["tracked_ips"],
    }
