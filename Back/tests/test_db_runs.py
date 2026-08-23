"""실행 기록의 **DB 경로**. 파일 경로는 tests/test_run_log.py 가 본다."""

from datetime import datetime, timezone

import pytest

from app.db import runs as runs_table
from app.services import run_log

pytestmark = pytest.mark.usefixtures("db")

RESULT = {
    "text": "요약 본문",
    "llm_ms": 1500,
    "input_tokens": 100,
    "output_tokens": 200,
    "cache_write_tokens": 400,
    "cache_read_tokens": 50,
    "cost_usd": 0.0123,
}


def test_records_round_trip_through_the_db():
    run_log.append_run(
        source="analyze",
        repo="psf/requests",
        model="claude-sonnet-5",
        effort="medium",
        fetch_ms=1200,
        context="컨텍스트 원문",
        system_prompt="시스템 프롬프트",
        result=RESULT,
    )

    [record] = run_log.read(10)
    assert record["source"] == "analyze"
    assert record["repo"] == "psf/requests"
    assert record["cached"] is False
    assert record["input_tokens"] == 100
    assert record["cache_write_tokens"] == 400
    assert record["cost_usd"] == 0.0123
    assert record["context_chars"] == len("컨텍스트 원문")
    assert record["summary"] == "요약 본문"


def test_cache_hit_is_recorded_with_zero_cost():
    run_log.append_cache_hit(
        source="analyze", repo="psf/requests", model="claude-sonnet-5",
        fetch_ms=30, summary="캐시된 요약",
    )

    [record] = run_log.read(10)
    assert record["cached"] is True
    assert record["input_tokens"] == 0
    assert record["cost_usd"] == 0.0


def test_stop_reason_round_trips_through_the_db():
    """열이 없으면 INSERT 가 깨진다 — FIELDS 와 schema.sql 이 함께 가는지 본다.

    **두 값을 다 넣는다.** 한 값만 보면 상수를 박아 넣어도 통과한다.
    """
    for reason in ("end_turn", "refusal"):
        run_log.append_run(
            source="chat", repo="psf/requests", model="m", effort=None,
            fetch_ms=1, context="c", system_prompt="s",
            result={**RESULT, "stop_reason": reason},
        )

    assert [r["stop_reason"] for r in run_log.read(10)] == ["refusal", "end_turn"]


def test_ts_is_an_iso_string_not_a_datetime():
    """usage_stats 가 `datetime.fromisoformat(record["ts"])` 로 파싱한다.

    DB 는 datetime 객체를 돌려주므로 그대로 넘기면 집계가 통째로 깨진다.
    파일 경로가 문자열이었으니 DB 경로도 문자열이어야 한다.
    """
    run_log.append_cache_hit(
        source="analyze", repo="a/b", model="m", fetch_ms=1, summary="s"
    )

    [record] = run_log.read(10)
    assert isinstance(record["ts"], str)
    parsed = datetime.fromisoformat(record["ts"])
    assert (datetime.now(timezone.utc) - parsed).total_seconds() < 60


def test_read_returns_newest_first_and_honours_the_limit():
    for i in range(5):
        run_log.append_cache_hit(
            source="analyze", repo=f"owner/repo{i}", model="m", fetch_ms=i, summary="s"
        )

    records = run_log.read(3)
    assert len(records) == 3
    assert [r["repo"] for r in records] == ["owner/repo4", "owner/repo3", "owner/repo2"]


def test_insert_keeps_a_supplied_timestamp():
    """마이그레이션은 옛 시각 그대로 넣어야 한다 — now() 로 덮으면 일자별 집계가 무너진다."""
    runs_table.insert(
        {"ts": "2026-08-14T08:43:41.998827+00:00", "source": "lab", "cached": False}
    )
    [record] = run_log.read(10)
    assert record["ts"].startswith("2026-08-14T08:43:41")


def test_usage_stats_reads_from_the_db():
    """집계가 새 저장소를 그대로 따라오는지 — read() 하나만 바꾸면 되도록 만들었다."""
    from app.services import usage_stats

    run_log.append_run(
        source="chat", repo="psf/requests", model="claude-sonnet-5", effort=None,
        fetch_ms=10, context="c", system_prompt="s", result=RESULT,
    )

    report = usage_stats.build_report(days=1)
    assert report["totals"]["llm_calls"] == 1
    assert report["totals"]["input_tokens"] == 100
    [chat_row] = [r for r in report["by_source"] if r["source"] == "chat"]
    assert chat_row["llm_calls"] == 1
