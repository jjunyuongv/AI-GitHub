"""runs.jsonl 집계 — 이 앱이 보낸 Claude 호출의 횟수·토큰·비용.

Anthropic Admin API(조직 실청구)는 개인 계정에서 못 쓰므로 로컬 기록으로 집계한다.
따라서 비용은 claude_client.pricing_for() 기반 추정치이고, 다른 곳에서 쓴 사용량은 포함되지 않는다.
기록된 cost_usd 를 그대로 합산한다 — 호출 시점의 단가로 이미 계산돼 있어서,
나중에 단가가 바뀌어도 지난 기록이 소급해 달라지지 않는다.
날짜 구분은 로컬 타임존 기준.
"""

from datetime import datetime, timedelta

from app.services import run_log

MAX_DAYS = 365
# cache_write_tokens 는 나중에 추가됐다. 그 전 기록은 0 으로 집계되지만 비용도 그때
# 계산된 값 그대로 남는다 — 옛 기록의 cost_usd 는 캐시 몫이 빠진 과소 추정이다.
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_write_tokens",
    "cache_read_tokens",
)


def time_range(days: int) -> tuple[datetime, datetime]:
    """오늘을 포함하는 [시작, 끝) 구간 (로컬 타임존)."""
    end = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    return end - timedelta(days=days), end


def _blank(**extra) -> dict:
    return {
        "calls": 0,
        "cache_hits": 0,
        "cost_usd": 0.0,
        "llm_ms": 0,
        **{f: 0 for f in TOKEN_FIELDS},
        **extra,
    }


def _accumulate(into: dict, record: dict) -> None:
    into["calls"] += 1
    # cached는 나중에 추가된 필드다. 없는 옛 기록은 전부 LLM을 실제로 호출한 것.
    if record.get("cached"):
        into["cache_hits"] += 1
    into["cost_usd"] += record.get("cost_usd") or 0.0
    into["llm_ms"] += record.get("llm_ms") or 0
    for field in TOKEN_FIELDS:
        into[field] += record.get(field) or 0


def _derive(stats: dict) -> dict:
    """비율·평균 파생값.

    캐시 히트는 LLM을 부르지 않았으므로 평균 LLM 시간의 분모에서 뺀다.
    포함시키면 히트가 늘수록 평균이 0 쪽으로 끌려가 실제 응답 속도를 못 읽는다.
    """
    llm_calls = stats["calls"] - stats["cache_hits"]
    return {
        **stats,
        "llm_calls": llm_calls,
        "hit_rate": round(stats["cache_hits"] / stats["calls"] * 100, 1) if stats["calls"] else 0.0,
        "avg_llm_ms": round(stats["llm_ms"] / llm_calls) if llm_calls else 0,
    }


def build_report(days: int = 7) -> dict:
    days = max(1, min(days, MAX_DAYS))
    start, end = time_range(days)

    totals = _blank()
    by_source: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    daily = {
        (start + timedelta(days=offset)).strftime("%Y-%m-%d"): _blank()
        for offset in range(days)
    }

    for record in run_log.read(limit=100_000):
        ts = datetime.fromisoformat(record["ts"]).astimezone()
        if not (start <= ts < end):
            continue
        _accumulate(totals, record)
        # source는 나중에 추가된 필드다. 없는 옛 기록은 전부 실험실에서 나온 것.
        _accumulate(by_source.setdefault(record.get("source") or "lab", _blank()), record)
        _accumulate(by_model.setdefault(record.get("model") or "(미분류)", _blank()), record)
        _accumulate(daily[ts.strftime("%Y-%m-%d")], record)

    def _rows(grouped: dict, key: str) -> list[dict]:
        rows = [{key: name, **_derive(stats)} for name, stats in grouped.items()]
        return sorted(rows, key=lambda row: row["calls"], reverse=True)

    return {
        "days": days,
        "starting_at": start.strftime("%Y-%m-%d"),
        "ending_at": (end - timedelta(days=1)).strftime("%Y-%m-%d"),
        "totals": _derive(totals),
        "by_source": _rows(by_source, "source"),
        "by_model": _rows(by_model, "model"),
        "daily": [{"date": date, **_derive(stats)} for date, stats in sorted(daily.items())],
    }
