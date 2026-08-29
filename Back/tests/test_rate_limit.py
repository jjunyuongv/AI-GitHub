import threading
import time
from datetime import datetime, timedelta

import pytest

from app.services import rate_limit
from app.services.rate_limit import RateLimitExceeded

IP = "203.0.113.7"


@pytest.fixture(autouse=True)
def state_file(tmp_path, monkeypatch):
    """**파일 경로**를 검증한다 (DB 경로는 tests/test_db_rate_limits.py).

    DATABASE_URL 이 설정된 개발 환경에서는 코드가 DB 를 먼저 쓰므로, 명시적으로 꺼서
    파일 구현이 계속 동작하는지 본다 — DB 없이도 상한이 걸려야 한다는 것이 이 경로의 존재 이유다.
    끄지 않으면 이 테스트가 개발 DB 의 카운터를 건드린다.
    """
    monkeypatch.setattr(rate_limit, "_use_db", lambda: False)
    path = tmp_path / "rate_limit.json"
    monkeypatch.setattr(rate_limit, "STATE_PATH", path)
    # 테스트마다 상한을 명시한다. 기본값이 바뀌어도 테스트가 흔들리지 않게.
    monkeypatch.setattr(rate_limit, "DAILY_LLM_CALL_LIMIT", 5)
    monkeypatch.setattr(rate_limit, "DAILY_TOKEN_LIMIT", 1000)
    monkeypatch.setattr(rate_limit, "IP_RATE_LIMIT", 3)
    monkeypatch.setattr(rate_limit, "IP_RATE_WINDOW_SECONDS", 3600)
    return path


class _FakeRequest:
    def __init__(self, headers=None, host="198.51.100.1"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})() if host else None


# --- 클라이언트 IP ----------------------------------------------------------


def test_uses_connection_ip_by_default(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", False)
    request = _FakeRequest({"x-forwarded-for": "1.2.3.4"}, host="198.51.100.1")

    # 헤더를 신뢰하지 않으면 위조해도 소용없다.
    assert rate_limit.client_ip(request) == "198.51.100.1"


def test_uses_forwarded_header_when_behind_proxy(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", True)
    request = _FakeRequest({"x-forwarded-for": "1.2.3.4, 10.0.0.1, 10.0.0.2"})

    # 맨 앞이 원 클라이언트다.
    assert rate_limit.client_ip(request) == "1.2.3.4"


def test_falls_back_to_real_ip_header(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", True)

    assert rate_limit.client_ip(_FakeRequest({"x-real-ip": "5.6.7.8"})) == "5.6.7.8"


def test_falls_back_to_connection_ip_when_headers_missing(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", True)

    assert rate_limit.client_ip(_FakeRequest({})) == "198.51.100.1"


def test_handles_missing_client(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", False)

    assert rate_limit.client_ip(_FakeRequest({}, host=None)) == "unknown"


# --- IP별 제한 --------------------------------------------------------------


def test_blocks_ip_after_limit():
    for _ in range(3):
        rate_limit.check_and_reserve(IP)

    with pytest.raises(RateLimitExceeded, match="너무 잦습니다"):
        rate_limit.check_and_reserve(IP)


def test_other_ips_are_unaffected():
    for _ in range(3):
        rate_limit.check_and_reserve(IP)

    rate_limit.check_and_reserve("198.51.100.99")  # 예외 없이 통과


def test_old_hits_leave_the_window(monkeypatch):
    monkeypatch.setattr(rate_limit, "IP_RATE_WINDOW_SECONDS", 60)
    for _ in range(3):
        rate_limit.check_and_reserve(IP)

    # 윈도우를 넘긴 시점으로 이동 (패치 전 원본을 잡아둬야 재귀하지 않는다)
    later = time.time() + 120
    monkeypatch.setattr(rate_limit.time, "time", lambda: later)

    rate_limit.check_and_reserve(IP)


# --- 일일 상한 --------------------------------------------------------------


def test_blocks_when_daily_call_limit_reached(monkeypatch):
    monkeypatch.setattr(rate_limit, "IP_RATE_LIMIT", 0)  # IP 제한은 끄고 본다
    for _ in range(5):
        rate_limit.check_and_reserve(IP)

    with pytest.raises(RateLimitExceeded, match="내일 다시"):
        rate_limit.check_and_reserve(IP)


def test_blocks_when_daily_token_limit_reached():
    rate_limit.record_tokens(1200)

    with pytest.raises(RateLimitExceeded, match="내일 다시"):
        rate_limit.check_and_reserve(IP)


def test_token_limit_is_judged_after_the_fact():
    """호출 전에는 쓸 토큰을 모르므로 상한을 넘기는 마지막 한 번은 통과한다."""
    rate_limit.record_tokens(999)

    rate_limit.check_and_reserve(IP)  # 아직 상한 미만이라 통과
    rate_limit.record_tokens(5000)  # 크게 넘겨버림

    with pytest.raises(RateLimitExceeded):
        rate_limit.check_and_reserve(IP)


def test_counters_reset_on_a_new_day(monkeypatch):
    monkeypatch.setattr(rate_limit, "IP_RATE_LIMIT", 0)
    for _ in range(5):
        rate_limit.check_and_reserve(IP)
    rate_limit.record_tokens(900)

    tomorrow = (datetime.now().astimezone() + timedelta(days=1)).strftime("%Y-%m-%d")
    monkeypatch.setattr(rate_limit, "_today", lambda: tomorrow)

    rate_limit.check_and_reserve(IP)
    assert rate_limit.today_usage()["calls"] == 1
    assert rate_limit.today_usage()["tokens"] == 0


def test_ip_window_survives_the_date_change(monkeypatch):
    """자정에 IP 기록까지 비우면 그 순간 제한이 풀려 우회 구멍이 된다."""
    for _ in range(3):
        rate_limit.check_and_reserve(IP)

    tomorrow = (datetime.now().astimezone() + timedelta(days=1)).strftime("%Y-%m-%d")
    monkeypatch.setattr(rate_limit, "_today", lambda: tomorrow)

    with pytest.raises(RateLimitExceeded, match="너무 잦습니다"):
        rate_limit.check_and_reserve(IP)


def test_ip_block_reports_retry_after_within_the_window():
    for _ in range(3):
        rate_limit.check_and_reserve(IP)

    with pytest.raises(RateLimitExceeded) as exc:
        rate_limit.check_and_reserve(IP)

    # 가장 오래된 요청이 빠져나갈 때까지 = 윈도우(3600초) 안쪽
    assert 0 < exc.value.retry_after <= 3600


def test_daily_block_reports_seconds_until_midnight(monkeypatch):
    monkeypatch.setattr(rate_limit, "IP_RATE_LIMIT", 0)
    for _ in range(5):
        rate_limit.check_and_reserve(IP)

    with pytest.raises(RateLimitExceeded) as exc:
        rate_limit.check_and_reserve(IP)

    assert 0 < exc.value.retry_after <= 86400


def test_zero_means_unlimited(monkeypatch):
    monkeypatch.setattr(rate_limit, "DAILY_LLM_CALL_LIMIT", 0)
    monkeypatch.setattr(rate_limit, "DAILY_TOKEN_LIMIT", 0)
    monkeypatch.setattr(rate_limit, "IP_RATE_LIMIT", 0)
    rate_limit.record_tokens(10_000_000)

    for _ in range(20):
        rate_limit.check_and_reserve(IP)


# --- 동시성 ----------------------------------------------------------------


def test_concurrent_requests_do_not_lose_counts(monkeypatch):
    monkeypatch.setattr(rate_limit, "DAILY_LLM_CALL_LIMIT", 0)
    monkeypatch.setattr(rate_limit, "IP_RATE_LIMIT", 0)

    def worker():
        for _ in range(10):
            rate_limit.check_and_reserve(IP)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # read-modify-write가 겹치면 50보다 작아진다.
    assert rate_limit.today_usage()["calls"] == 50


def test_concurrent_token_records_do_not_lose_counts():
    def worker():
        for _ in range(10):
            rate_limit.record_tokens(1)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert rate_limit.today_usage()["tokens"] == 50


# --- 오늘 사용량 요약 --------------------------------------------------------


def test_today_usage_reports_percentages():
    rate_limit.check_and_reserve(IP)
    rate_limit.record_tokens(500)

    usage = rate_limit.today_usage()

    assert usage["calls"] == 1
    assert usage["call_limit"] == 5
    assert usage["calls_pct"] == 20.0
    assert usage["tokens_pct"] == 50.0
    assert usage["tracked_ips"] == 1


def test_percentage_is_none_when_limit_is_off(monkeypatch):
    monkeypatch.setattr(rate_limit, "DAILY_TOKEN_LIMIT", 0)

    assert rate_limit.today_usage()["tokens_pct"] is None


# --- 저장 실패해도 서비스는 계속 --------------------------------------------


def test_corrupt_state_file_is_ignored(state_file):
    state_file.write_text("{망가진", encoding="utf-8")

    rate_limit.check_and_reserve(IP)  # 예외 없이 진행


def test_unwritable_state_does_not_raise(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("디스크 오류")

    monkeypatch.setattr(rate_limit.Path, "write_text", boom)

    rate_limit.check_and_reserve(IP)


def test_the_file_path_ignores_the_user_layer():
    """**파일 폴백에는 사용자 층이 없다.** 그리고 없는 것이 맞다.

    로그인은 DB 가 있어야 성립하므로(`logins` 표가 거기 있다) 이 경로에 로그인한
    요청이 도달할 수 없다. 여기서 고정하는 것은 "user_id 를 줘도 동작이 안 바뀐다" 다 —
    쓰지 않는 분기를 나중에 누가 채워 넣으면 두 경로의 상한이 갈린다.
    """
    for _ in range(3):
        rate_limit.check_and_reserve(IP, 7)

    with pytest.raises(RateLimitExceeded):
        rate_limit.check_and_reserve(IP, 7)
