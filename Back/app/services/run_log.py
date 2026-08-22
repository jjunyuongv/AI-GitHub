"""실행 기록.

**DB 를 쓸 수 있으면 `runs` 테이블에, 아니면 Back/logs/runs.jsonl 에 남긴다.**

DB 를 먼저 보는 이유는 다중 워커다 — 워커가 여럿이면 파일에 동시에 append 하게 되고
집계도 워커마다 다른 파일 상태를 보게 된다. 그렇다고 DB 를 **요구**하지는 않는다.
DATABASE_URL 없이도 서비스가 도는 것이 이 프로젝트의 방침이라(요약 캐시·대화만 꺼진다),
기록이 그 방침을 깨면 안 된다.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.db import pool
from app.db import runs as runs_table
from app.db.pool import DB_ERRORS

LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "runs.jsonl"

logger = logging.getLogger(__name__)


def _append_to_file(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def append(record: dict) -> dict:
    """기록을 남긴다. 쓰기에 실패해도 예외를 올리지 않는다.

    이 함수는 LLM 호출이 끝난 뒤에 불린다. 여기서 예외가 나면 토큰은 이미 쓴 채로
    사용자는 요약을 못 받는다 — 기록을 잃는 편이 낫다. summary_cache·rate_limit도 같은 방침.

    **DB 가 켜져 있는데 쓰기가 실패하면 파일로 떨어뜨리지 않는다.** 두 곳에 나뉘면
    집계가 갈리고, 어느 쪽이 진실인지 알 수 없게 된다. 경고만 남기고 그 기록을 버린다.
    """
    record["ts"] = datetime.now(timezone.utc).isoformat()
    try:
        if pool.is_enabled():
            runs_table.insert(record)
        else:
            _append_to_file(record)
    except (OSError, *DB_ERRORS) as e:
        logger.warning("실행 기록을 쓰지 못했습니다: %s", e)
    return record


def append_run(
    *,
    source: str,
    repo: str,
    model: str,
    effort: str | None,
    fetch_ms: int,
    context: str,
    system_prompt: str,
    result: dict,
) -> dict:
    """run_summary() 결과를 기록 한 줄로 만들어 저장한다. source는 "lab" | "analyze"."""
    return append(
        {
            "source": source,
            "cached": False,
            "repo": repo,
            "model": model,
            "effort": effort,
            "fetch_ms": fetch_ms,
            "llm_ms": result["llm_ms"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "cache_write_tokens": result["cache_write_tokens"],
            "cache_read_tokens": result["cache_read_tokens"],
            "cost_usd": result["cost_usd"],
            "context_chars": len(context),
            "system_prompt": system_prompt,
            "summary": result["text"],
            # 도구 루프를 거친 결과에만 있다. 요약은 한 번에 끝나므로 0.
            "round_trips": result.get("round_trips", 0),
        }
    )


def append_cache_hit(
    *,
    source: str,
    repo: str,
    model: str,
    fetch_ms: int,
    summary: str,
) -> dict:
    """캐시 히트 기록. LLM을 부르지 않았으므로 토큰·비용·LLM 시간은 모두 0이다.

    model은 그 요약을 만들 때 쓴 모델이다 (이번에 호출한 모델이 아니다).
    """
    return append(
        {
            "source": source,
            "cached": True,
            "repo": repo,
            "model": model,
            "effort": None,
            "fetch_ms": fetch_ms,
            "llm_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_write_tokens": 0,
            "cache_read_tokens": 0,
            "cost_usd": 0.0,
            "context_chars": 0,
            "system_prompt": "",
            "summary": summary,
            "round_trips": 0,
        }
    )


def read(limit: int = 100) -> list[dict]:
    """최근 기록을 최신순으로. 쓴 곳에서 읽는다(DB 우선, 없으면 파일).

    DB 조회가 실패하면 파일로 넘어간다 — 관리자 화면이 DB 장애로 빈 표가 되는 것보다
    **마이그레이션 전 기록이라도 보이는 편**이 낫다. 읽기는 집계를 갈라놓지 않는다.
    """
    if pool.is_enabled():
        try:
            return runs_table.read(limit)
        except DB_ERRORS as e:
            logger.warning("실행 기록을 DB 에서 읽지 못해 파일을 봅니다: %s", e)

    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    records = []
    for line in reversed(lines):
        if len(records) >= limit:
            break
        if line.strip():
            records.append(json.loads(line))
    return records
