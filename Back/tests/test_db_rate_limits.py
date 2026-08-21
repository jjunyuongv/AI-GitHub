"""남용 방지의 **DB 경로**. 파일 경로는 tests/test_rate_limit.py 가 본다.

이 경로가 존재하는 이유는 다중 워커다. 파일 구현은 프로세스 안 `threading.Lock` 으로
직렬화하는데 워커가 여럿이면 Lock 이 워커마다 따로라 상한이 워커 수만큼 느슨해진다.
**여기서 검증할 것은 그 Lock 없이도 카운트가 정확한가**이고, 아래 동시성 테스트가 그것이다.
"""

import threading

import pytest

from app.db import rate_limits as store

pytestmark = pytest.mark.usefixtures("db")

DAY = "2026-08-19"
IP = "203.0.113.9"

# 상한을 인자로 넘기므로 테스트마다 명시한다 — 설정 기본값이 바뀌어도 흔들리지 않는다.
LIMITS = {
    "call_limit": 5,
    "token_limit": 1000,
    "ip_limit": 3,
    "window_seconds": 3600,
    "seconds_until_tomorrow": 7200,
}


def reserve(ip=IP, **overrides):
    return store.reserve(DAY, ip, **{**LIMITS, **overrides})


def test_reserve_passes_until_the_ip_limit():
    assert reserve() is None
    assert reserve() is None
    assert reserve() is None

    rejected = reserve()
    assert rejected is not None
    assert "너무 잦" in rejected["reason"]
    # 남은 시간은 가장 오래된 요청이 윈도우를 빠져나갈 때까지다.
    assert 0 < rejected["retry_after"] <= LIMITS["window_seconds"]


def test_other_ips_are_unaffected():
    for _ in range(3):
        reserve()
    assert reserve() is not None
    assert reserve(ip="198.51.100.1") is None


def test_rejected_request_does_not_consume_the_daily_count():
    """거절된 요청이 카운터를 올려놓고 가면 안 된다 — 트랜잭션이 통째로 되돌아가야 한다."""
    for _ in range(3):
        reserve()
    assert store.usage(DAY, 3600)["calls"] == 3

    assert reserve() is not None  # IP 상한에 막힘
    assert store.usage(DAY, 3600)["calls"] == 3, "막힌 요청이 일일 카운터를 올렸다"


def test_daily_call_limit_blocks():
    # IP 제한은 꺼서 일일 상한만 본다.
    for _ in range(5):
        assert reserve(ip_limit=0) is None
    rejected = reserve(ip_limit=0)
    assert rejected is not None
    assert "오늘" in rejected["reason"]
    assert rejected["retry_after"] == LIMITS["seconds_until_tomorrow"]


def test_token_limit_is_judged_after_the_fact():
    """호출 전에는 쓸 토큰을 모른다 — 상한을 넘기는 마지막 한 번은 통과한다."""
    assert reserve(ip_limit=0) is None
    store.add_tokens(DAY, 1500)  # 상한(1000)을 넘겼다
    assert reserve(ip_limit=0) is not None


def test_zero_limits_disable_each_check():
    for _ in range(20):
        assert reserve(ip_limit=0, call_limit=0, token_limit=0) is None


def test_add_tokens_accumulates():
    store.add_tokens(DAY, 100)
    store.add_tokens(DAY, 250)
    assert store.usage(DAY, 3600)["tokens"] == 350


def test_usage_reports_tracked_ips():
    reserve(ip="198.51.100.1")
    reserve(ip="198.51.100.2")
    usage = store.usage(DAY, 3600)
    assert usage["calls"] == 2
    assert usage["tracked_ips"] == 2


def test_concurrent_reserves_do_not_lose_counts():
    """**이 과제의 핵심.** Lock 없이 SQL 만으로 카운트가 정확한가.

    파일 구현은 threading.Lock 으로 이걸 지키는데, 워커가 여럿이면 그 Lock 이
    무력해진다. DB 경로는 `INSERT … ON CONFLICT DO UPDATE … RETURNING` 한 문장으로
    증가와 확인을 함께 하므로 스레드든 프로세스든 같은 결과가 나와야 한다.
    """
    threads = 5
    per_thread = 10
    errors = []

    def worker(n):
        try:
            for _ in range(per_thread):
                # 상한은 전부 끄고 **세는 것만** 본다. 막히면 카운트가 안 늘어
                # 무엇이 새는지 가릴 수 없다.
                reserve(ip=f"198.51.100.{n}", ip_limit=0, call_limit=0, token_limit=0)
        except Exception as e:  # 스레드 예외는 조용히 사라진다 — 모아서 드러낸다
            errors.append(e)

    workers = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()

    assert not errors, errors
    assert store.usage(DAY, 3600)["calls"] == threads * per_thread


def test_concurrent_token_records_do_not_lose_counts():
    """토큰 누적도 같은 이유로 원자적이어야 한다."""
    threads = 5
    per_thread = 10
    for_each = 7

    workers = [
        threading.Thread(
            target=lambda: [store.add_tokens(DAY, for_each) for _ in range(per_thread)]
        )
        for _ in range(threads)
    ]
    for t in workers:
        t.start()
    for t in workers:
        t.join()

    assert store.usage(DAY, 3600)["tokens"] == threads * per_thread * for_each


def test_usage_prunes_hits_outside_the_window():
    """다시 오지 않는 IP 의 기록은 reserve 가 치우지 못한다 — usage 가 전체를 정리한다."""
    reserve(ip="198.51.100.5")
    assert store.usage(DAY, 3600)["tracked_ips"] == 1
    # 윈도우를 0 으로 보면 방금 넣은 것도 밖이다.
    assert store.usage(DAY, 0)["tracked_ips"] == 0
