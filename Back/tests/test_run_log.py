import json

import pytest

from app.services import run_log

RESULT = {
    "text": "요약",
    "llm_ms": 1500,
    "input_tokens": 100,
    "output_tokens": 200,
    "cache_write_tokens": 400,
    "cache_read_tokens": 50,
    "cost_usd": 0.01,
}


@pytest.fixture(autouse=True)
def log_file(tmp_path, monkeypatch):
    """**파일 경로**를 검증한다 (DB 경로는 tests/test_db_runs.py).

    DATABASE_URL 이 설정된 개발 환경에서는 코드가 DB 를 먼저 쓰므로 명시적으로 끈다.
    끄지 않으면 이 테스트가 개발 DB 에 기록을 남긴다.
    """
    monkeypatch.setattr(run_log.pool, "DATABASE_URL", "")
    path = tmp_path / "runs.jsonl"
    monkeypatch.setattr(run_log, "LOG_PATH", path)
    return path


def test_llm_run_is_marked_not_cached():
    record = run_log.append_run(
        source="analyze",
        repo="psf/requests",
        model="claude-sonnet-5",
        effort="medium",
        fetch_ms=300,
        context="컨텍스트",
        system_prompt="시스템",
        result=RESULT,
    )

    assert record["cached"] is False
    assert record["input_tokens"] == 100


def test_cache_hit_records_zero_llm_usage():
    record = run_log.append_cache_hit(
        source="analyze",
        repo="psf/requests",
        model="claude-sonnet-5",
        fetch_ms=250,
        summary="캐시된 요약",
    )

    assert record["cached"] is True
    assert record["llm_ms"] == 0
    assert record["input_tokens"] == 0
    assert record["output_tokens"] == 0
    assert record["cache_read_tokens"] == 0
    assert record["cost_usd"] == 0.0
    assert record["summary"] == "캐시된 요약"
    assert record["fetch_ms"] == 250  # GitHub 조회는 실제로 했다


def test_both_kinds_share_the_same_fields():
    """기록 표·집계가 두 종류를 같은 모양으로 읽을 수 있어야 한다."""
    run = run_log.append_run(
        source="analyze",
        repo="psf/requests",
        model="m",
        effort=None,
        fetch_ms=1,
        context="",
        system_prompt="",
        result=RESULT,
    )
    hit = run_log.append_cache_hit(
        source="analyze", repo="psf/requests", model="m", fetch_ms=1, summary="요약"
    )

    assert set(run) == set(hit)


def test_unwritable_log_does_not_raise(monkeypatch):
    """LLM 호출이 끝난 뒤에 불리므로, 여기서 예외가 나면 토큰만 쓰고 응답을 잃는다."""

    def boom(*args, **kwargs):
        raise OSError("디스크 오류")

    monkeypatch.setattr(run_log.Path, "open", boom)

    record = run_log.append_cache_hit(
        source="analyze", repo="psf/requests", model="m", fetch_ms=1, summary="요약"
    )

    assert record["summary"] == "요약"


def test_records_round_trip_through_the_file(log_file):
    run_log.append_cache_hit(
        source="analyze", repo="psf/requests", model="m", fetch_ms=1, summary="요약"
    )

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()

    assert json.loads(lines[0])["cached"] is True
    assert run_log.read()[0]["cached"] is True
