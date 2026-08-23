"""실행 기록(runs) 테이블 접근.

`services/run_log.py` 가 DB 를 쓸 수 있을 때 이 모듈로 내려온다. 쓸 수 없으면
그쪽이 파일(logs/runs.jsonl)로 폴백하므로, 여기서는 DB 가 있다고 가정한다.
"""

from datetime import datetime, timezone

from app.db.pool import cursor

# 기록 한 줄의 열. append 와 read 가 같은 목록을 봐야 필드가 어긋나지 않는다.
FIELDS = (
    "source",
    "cached",
    "repo",
    "model",
    "effort",
    "fetch_ms",
    "llm_ms",
    "input_tokens",
    "output_tokens",
    "cache_write_tokens",
    "cache_read_tokens",
    "cost_usd",
    "context_chars",
    "system_prompt",
    "summary",
    # 도구를 몇 번 불렀는가. 도구를 안 쓰는 경로는 0 이다.
    "round_trips",
    # 마지막 호출이 끝난 이유. 캐시 히트는 None 이다.
    "stop_reason",
)


def insert(record: dict) -> None:
    """기록 한 줄을 넣는다. ts 가 있으면 그 값을 쓴다(마이그레이션이 옛 시각을 넘긴다)."""
    values = [record.get(name) for name in FIELDS]
    ts = record.get("ts")
    with cursor() as cur:
        cur.execute(
            f"""INSERT INTO runs (ts, {", ".join(FIELDS)})
                VALUES (COALESCE(%s, now()), {", ".join(["%s"] * len(FIELDS))})""",
            [ts, *values],
        )


def read(limit: int) -> list[dict]:
    """최근 기록을 최신순으로.

    `ts` 는 **ISO 문자열로 돌려준다** — 파일 경로가 그랬고, usage_stats 가
    `datetime.fromisoformat()` 으로 파싱한다. 여기서 datetime 객체를 주면 그쪽이 깨진다.
    """
    with cursor(commit=False) as cur:
        cur.execute(
            f"""SELECT ts, {", ".join(FIELDS)} FROM runs
                 ORDER BY ts DESC, id DESC LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()

    out = []
    for row in rows:
        record = dict(row)
        ts = record["ts"]
        if isinstance(ts, datetime):
            record["ts"] = ts.astimezone(timezone.utc).isoformat()
        out.append(record)
    return out


def count() -> int:
    with cursor(commit=False) as cur:
        cur.execute("SELECT count(*) AS n FROM runs")
        return cur.fetchone()["n"]
