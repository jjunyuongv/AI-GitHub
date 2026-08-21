"""코드 검색 품질 측정 기록. Back/logs/search_evals.jsonl 에 한 줄씩 append.

측정은 tests/test_search_quality.py 가 수행하고, 여기는 저장과 조회만 한다 —
관리자 페이지(/admin/search)가 같은 파일을 읽어 모델끼리 비교하기 때문에
읽기 로직이 테스트 안에 있으면 안 된다 (run_log.py 와 같은 구조).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "search_evals.jsonl"

logger = logging.getLogger(__name__)


def summarize(rows: list[dict], total_chunks: int) -> dict:
    """질의별 결과에서 지표를 뽑는다.

    rank 는 1부터 시작하는 정답 순위이고, 정답을 못 찾았으면 None 이다.
    못 찾은 질의를 평균에서 빼면 나쁜 모델이 좋아 보이므로, 평균 순위는
    찾은 것만으로 계산하되 **found 비율을 함께** 싣는다.
    """
    ranks = [r["rank"] for r in rows if r["rank"]]
    n = len(rows)
    if not n:
        return {}
    return {
        # 못 찾은 질의는 1/rank 를 0 으로 본다 (MRR 의 표준 처리)
        "mrr": round(sum(1 / r["rank"] for r in rows if r["rank"]) / n, 4),
        "recall_at_8": round(sum(1 for r in rows if r["rank"] and r["rank"] <= 8) / n, 4),
        "recall_at_3": round(sum(1 for r in rows if r["rank"] and r["rank"] <= 3) / n, 4),
        "recall_at_1": round(sum(1 for r in rows if r["rank"] == 1) / n, 4),
        "mean_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "found": len(ranks),
        "total": n,
        "total_chunks": total_chunks,
    }


def append_eval(
    *,
    model: str,
    dim: int,
    table: str,
    repo: str,
    rows: list[dict],
    total_chunks: int,
    set_version: int = 1,
    index_ms: dict | None = None,
    peak_memory_mb: float | None = None,
    truncated_chunks: int | None = None,
    note: str = "",
) -> dict:
    """측정 한 번을 기록한다. 쓰기 실패는 경고만 남긴다(run_log 와 같은 방침)."""
    by_kind = {}
    for kind in {r["kind"] for r in rows}:
        by_kind[kind] = summarize([r for r in rows if r["kind"] == kind], total_chunks)

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "dim": dim,
        "table": table,
        "repo": repo,
        "set_version": set_version,
        "index_ms": index_ms or {},
        "peak_memory_mb": peak_memory_mb,
        "truncated_chunks": truncated_chunks,
        "note": note,
        "summary": summarize(rows, total_chunks),
        "by_kind": by_kind,
        "queries": rows,
    }
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("검색 평가 기록을 쓰지 못했습니다 (%s): %s", LOG_PATH, e)
    return record


def read(limit: int = 50) -> list[dict]:
    """최근 측정을 최신순으로."""
    if not LOG_PATH.exists():
        return []
    records = []
    for line in reversed(LOG_PATH.read_text(encoding="utf-8").splitlines()):
        if len(records) >= limit:
            break
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # 쓰다 만 줄이 있어도 나머지는 읽는다
                logger.warning("검색 평가 기록 한 줄을 건너뜁니다 (JSON 파손).")
    return records


def latest_per_model(limit: int = 50) -> list[dict]:
    """조합마다 가장 최근 측정만. 비교 표의 기본 재료다.

    키에 note 를 넣는 이유: 같은 모델·같은 테이블이라도 **주변 조건이 다르면 다른 실험**이다.
    (용어 사전을 켜고 끈 두 측정이 모델만으로는 구분되지 않아 하나가 사라졌었다.)
    repo 도 같은 이유로 키에 있다 — 저장소가 다르면 질의도 정답도 다른 실험이다.

    set_version 도 같다 — **평가셋의 정답 조건이 바뀌면 수치를 비교할 수 없다.**
    v1 은 정답 판정이 헐거워 v2 보다 후하게 나온다. 버전이 키에 없으면 그 둘이 한 칸에
    겹쳐 하나가 사라진다. 기록이 없는 옛 항목은 v1 로 본다.
    """
    seen: dict[tuple, dict] = {}
    for record in read(limit):
        key = (
            record.get("model"), record.get("table"),
            record.get("repo"), record.get("set_version", 1), record.get("note"),
        )
        if key not in seen:
            seen[key] = record
    return list(seen.values())
