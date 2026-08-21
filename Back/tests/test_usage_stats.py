from datetime import datetime, timedelta, timezone

import pytest

from app.services import usage_stats


def _record(*, cached=False, llm_ms=0, cost=0.0, tokens=0, source="analyze", model="m"):
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "repo": "psf/requests",
        "model": model,
        "llm_ms": llm_ms,
        "cost_usd": cost,
        "input_tokens": tokens,
        "output_tokens": tokens,
        "cache_read_tokens": 0,
    }
    if cached:
        record["cached"] = True
    return record


@pytest.fixture
def logged(monkeypatch):
    """run_log.read() 가 돌려줄 기록을 지정한다."""

    def _install(records):
        monkeypatch.setattr(usage_stats.run_log, "read", lambda limit=100: records)

    return _install


def test_hit_rate_counts_cached_records(logged):
    logged([_record(cached=True), _record(cached=True), _record(llm_ms=2000, cost=0.01)])

    totals = usage_stats.build_report(days=7)["totals"]

    assert totals["calls"] == 3
    assert totals["cache_hits"] == 2
    assert totals["llm_calls"] == 1
    assert totals["hit_rate"] == pytest.approx(66.7)


def test_no_hits_means_zero_rate(logged):
    logged([_record(llm_ms=1000), _record(llm_ms=1000)])

    totals = usage_stats.build_report(days=7)["totals"]

    assert totals["cache_hits"] == 0
    assert totals["hit_rate"] == 0.0


def test_old_records_without_cached_field_count_as_llm_calls(logged):
    """cached는 나중에 추가된 필드다. 없는 옛 기록이 히트로 잡히면 안 된다."""
    logged([{"ts": datetime.now(timezone.utc).isoformat(), "source": "lab", "model": "m"}])

    totals = usage_stats.build_report(days=7)["totals"]

    assert totals["cache_hits"] == 0
    assert totals["llm_calls"] == 1


def test_empty_log_does_not_divide_by_zero(logged):
    logged([])

    totals = usage_stats.build_report(days=7)["totals"]

    assert totals["hit_rate"] == 0.0
    assert totals["avg_llm_ms"] == 0


def test_cache_hits_are_excluded_from_average_llm_time(logged):
    """히트(llm_ms=0)를 평균에 넣으면 실제 응답 속도가 왜곡된다."""
    logged([_record(cached=True), _record(cached=True), _record(llm_ms=3000)])

    totals = usage_stats.build_report(days=7)["totals"]

    assert totals["avg_llm_ms"] == 3000  # 3000/1 이지 3000/3 이 아니다


def test_hit_rate_is_broken_down_by_source(logged):
    logged(
        [
            _record(source="analyze", cached=True),
            _record(source="analyze", llm_ms=1000),
            _record(source="lab", llm_ms=1000),
        ]
    )

    by_source = {r["source"]: r for r in usage_stats.build_report(days=7)["by_source"]}

    assert by_source["analyze"]["hit_rate"] == 50.0
    assert by_source["lab"]["hit_rate"] == 0.0


def test_daily_rows_carry_hit_rate(logged):
    logged([_record(cached=True), _record(llm_ms=1000)])

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    daily = {d["date"]: d for d in usage_stats.build_report(days=7)["daily"]}

    assert daily[today]["hit_rate"] == 50.0
    # 기록이 없는 날도 0으로 채워진다
    yesterday = (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert daily[yesterday]["calls"] == 0
    assert daily[yesterday]["hit_rate"] == 0.0
