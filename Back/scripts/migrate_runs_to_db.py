"""logs/runs.jsonl 을 runs 테이블로 옮긴다.

    python scripts/migrate_runs_to_db.py           # 미리보기
    python scripts/migrate_runs_to_db.py --apply   # 실제 이관

**파일을 지우지 않는다.** 이관이 잘못돼도 원본이 남아 있어야 다시 할 수 있고,
DATABASE_URL 을 비우면 코드가 그 파일로 돌아간다.

**두 번 돌려도 중복되지 않는다** — 이미 있는 ts 는 건너뛴다. 같은 순간에 두 건이
기록되는 일이 없어(호출 하나당 한 줄) ts 가 사실상 고유하다.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import pool  # noqa: E402
from app.db import runs as runs_table  # noqa: E402
from app.services.run_log import LOG_PATH  # noqa: E402


def _filled(record: dict) -> dict:
    """옛 기록에 없는 필드를 채운다. **화면이 지금까지 해석해 온 것과 같은 값이다.**

    `source` 는 프론트 호출을 로깅하면서, `cached` 는 캐시 히트를 기록하면서 생겼다.
    그 전 기록에는 열이 아예 없어서 `usage_stats` 와 관리자 화면이 각각
    "없으면 lab", "없으면 LLM 호출"로 읽어 왔다 (히트로 오인하면 절감량이 부풀려진다).
    이관하면서 그 해석을 값으로 고정한다 — 읽는 쪽마다 추측하지 않아도 된다.
    """
    record.setdefault("source", "lab")
    record.setdefault("cached", False)
    return record


def main() -> int:
    apply = "--apply" in sys.argv

    if not pool.is_enabled():
        print("DATABASE_URL 이 없습니다. .env 를 확인하세요.")
        return 1
    if not LOG_PATH.exists():
        print(f"옮길 파일이 없습니다: {LOG_PATH}")
        return 0

    pool.init_schema()

    records = [
        _filled(json.loads(line))
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"파일 {len(records)}건 · DB {runs_table.count()}건")

    with pool.cursor(commit=False) as cur:
        cur.execute("SELECT ts FROM runs")
        existing = {row["ts"].isoformat() for row in cur.fetchall()}

    todo = [r for r in records if r.get("ts") not in existing]
    print(f"옮길 것 {len(todo)}건 (이미 있는 {len(records) - len(todo)}건은 건너뜀)")

    if not apply:
        print("\n미리보기입니다. 실제로 옮기려면 --apply 를 붙이세요.")
        return 0

    for record in todo:
        runs_table.insert(record)

    print(f"\n이관 완료. DB {runs_table.count()}건")

    # 옮긴 뒤 합계가 맞는지 — 건수만 같고 값이 틀리면 집계가 조용히 달라진다.
    with pool.cursor(commit=False) as cur:
        cur.execute(
            "SELECT count(*) AS n, sum(input_tokens) AS inp,"
            " sum(output_tokens) AS out, sum(cost_usd) AS cost FROM runs"
        )
        db = cur.fetchone()

    def total(field):
        return sum(r.get(field) or 0 for r in records)

    print(f"  건수   파일 {len(records)} / DB {db['n']}")
    print(f"  입력   파일 {total('input_tokens'):,} / DB {db['inp'] or 0:,}")
    print(f"  출력   파일 {total('output_tokens'):,} / DB {db['out'] or 0:,}")
    print(f"  비용   파일 {total('cost_usd'):.4f} / DB {db['cost'] or 0:.4f}")
    print(f"\n원본은 그대로 둔다: {LOG_PATH}")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        # 풀을 열어 둔 채 인터프리터가 끝나면 psycopg_pool 이 종료 시점에
        # 워커를 join 하려다 PythonFinalizationError 를 뱉는다.
        pool.close()
    raise SystemExit(code)
