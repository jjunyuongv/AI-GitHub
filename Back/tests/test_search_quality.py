"""코드 검색 품질 측정.

일반 테스트가 아니다 — GitHub 에서 tarball 을 받고 수백 개 청크를 임베딩하므로
수십 초에서 수 분이 걸린다. `-m evaluation` 을 붙였을 때만 돈다.

    pytest -m evaluation tests/test_search_quality.py -s

측정 대상은 config.CHUNK_TABLE / EMBEDDING_MODEL 이 가리키는 조합이다.
모델을 바꿔 A/B 하려면 환경변수를 바꾸고 다시 돌린다:

    $env:EMBEDDING_MODEL="intfloat/multilingual-e5-large"
    $env:EMBEDDING_DIM="1024"
    $env:EMBEDDING_QUERY_PREFIX="query: "
    $env:EMBEDDING_PASSAGE_PREFIX="passage: "
    $env:CHUNK_TABLE="code_chunks_1024"

결과는 Back/logs/search_evals.jsonl 에 쌓이고 /admin/search 에서 비교한다.
LLM 은 부르지 않는다 (임베딩은 로컬이라 무과금).
"""

import json
import time
import tracemalloc
from pathlib import Path

import pytest

from app import config
from app.core import embeddings
from app.core.chunk_rule import rule_version
from app.core.chunker import chunk_files
from app.db import chunks as chunk_store
from app.db import index_status, pool
from app.services import search_eval_log
from app.services.github_client import fetch_source_files
from app.services.indexer import search_code
from tests.search_eval_dataset import (
    EVAL_SET_VERSION,
    EVAL_SETS,
    expected_label,
    is_answer,
)

pytestmark = pytest.mark.evaluation

# 정답이 몇 위인지 알려면 상위 K 개가 아니라 **전체 순위**가 필요하다.
FULL_RANKING_LIMIT = 100_000

# 받아 둔 소스를 재사용할 위치. cache/ 는 .gitignore 에 이미 들어 있다.
SOURCE_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "eval_sources"


def _snapshot_for(repo: tuple[str, str]) -> int:
    """평가용 스냅샷. 개발 DB 에 없으면 만든다 (대화 이력은 건드리지 않는다)."""
    if not pool.is_enabled():
        pytest.skip("DATABASE_URL 이 없어 검색 품질 측정을 건너뜁니다.")
    try:
        pool.init_schema()
    except Exception as e:
        pytest.skip(f"DB 에 붙을 수 없어 건너뜁니다: {e}")

    owner, name = repo
    with pool.cursor() as cur:
        cur.execute(
            """INSERT INTO repos (owner, name, display_owner, display_name)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (owner, name) DO UPDATE SET last_seen_at = now()
               RETURNING id""",
            (owner, name, owner, name),
        )
        repo_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO repo_snapshots (repo_id, key_source, version, context, summary, model)
               VALUES (%s, 'eval', 'fixed', '', '', 'eval')
               ON CONFLICT (repo_id, key_source, version) DO UPDATE SET model = 'eval'
               RETURNING id""",
            (repo_id,),
        )
        return cur.fetchone()["id"]


def _source_files(repo: tuple[str, str]) -> dict[str, str]:
    """평가용 소스. 로컬 캐시가 있으면 그것을 쓰고, 없으면 받아서 남긴다.

    청킹 규칙을 바꿔가며 여러 번 재는데 그때마다 tarball 을 받을 이유가 없다
    (marryday 는 15초 + GitHub 요청). 같은 커밋을 반복해 받지 않는 것이자,
    **측정끼리 같은 입력을 보장**하는 장치이기도 하다.
    캐시를 지우면 다음 실행에서 최신 소스로 다시 만들어진다.
    """
    cache = SOURCE_CACHE_DIR / f"{repo[0]}__{repo[1]}.json".lower()
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    files = fetch_source_files(*repo)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(files, ensure_ascii=False), encoding="utf-8")
    return files


def _index(snapshot: int, repo: tuple[str, str]) -> dict:
    """평가 대상 스냅샷을 현재 설정(모델·테이블)으로 인덱싱하고 비용을 잰다.

    indexer.start() 를 쓰지 않는다 — 이미 인덱싱돼 있으면 건너뛰고 큐를 통해 백그라운드로
    도는 게 그 함수의 일인데, 측정에서는 매번 같은 조건으로 다시 만들어야 비교가 성립한다.

    **다만 빌드는 정식으로 만들고 완료시킨다.** 전에는 replace_chunks() 만 부르고
    완료 처리를 건너뛰어서, 기록된 청크 수가 실제와 어긋난 채 남았다(기록 4,364 / 실제 3,033).
    """
    started = time.perf_counter()
    files = _source_files(repo)
    fetch_ms = int((time.perf_counter() - started) * 1000)

    pieces = chunk_files(
        files, count_tokens=embeddings.count_tokens, token_limit=embeddings.input_limit()
    )
    chunk_ms = int((time.perf_counter() - started) * 1000) - fetch_ms

    texts = [p["content"] for p in pieces]
    token_counts = embeddings.count_tokens(texts)

    tracemalloc.start()
    embed_started = time.perf_counter()
    vectors = embeddings.embed_documents(texts)
    embed_ms = int((time.perf_counter() - embed_started) * 1000)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    store_started = time.perf_counter()
    build_id = index_status.begin(
        snapshot, table=config.CHUNK_TABLE, chunk_rule=rule_version()
    )
    if build_id is None:  # 앞선 측정이 중간에 끊겨 running 으로 남은 경우
        index_status.reset_running()
        build_id = index_status.begin(
            snapshot, table=config.CHUNK_TABLE, chunk_rule=rule_version()
        )
    saved = chunk_store.insert_chunks(
        build_id, snapshot, pieces, vectors, table=config.CHUNK_TABLE
    )
    index_status.complete(build_id, saved)
    # 측정마다 빌드가 쌓이면 평가용 스냅샷이 계속 커진다. 보관 정책을 그대로 적용한다.
    index_status.prune_builds(snapshot, table=config.CHUNK_TABLE)
    store_ms = int((time.perf_counter() - store_started) * 1000)

    return {
        "chunks": len(pieces),
        "files": len(files),
        "build_id": build_id,
        "index_ms": {
            "fetch": fetch_ms, "chunk": chunk_ms, "embed": embed_ms, "store": store_ms,
        },
        "peak_memory_mb": round(peak / (1024 * 1024), 1),
        "token_counts": token_counts,
    }


@pytest.mark.parametrize("set_name", list(EVAL_SETS))
def test_measure_search_quality(set_name, capsys):
    """평가셋 전체를 돌려 정답 순위를 재고 기록한다. 단정하지 않고 측정만 한다.

    저장소마다 따로 돈다 — 청킹 규칙이 한 언어(Java)에만 맞춰진 것은 아닌지 보려면
    언어가 다른 저장소에서도 같은 지표를 재야 한다.
    """
    spec = EVAL_SETS[set_name]
    snapshot_id = _snapshot_for(spec["repo"])
    stats = _index(snapshot_id, spec["repo"])

    rows = []
    for case in spec["queries"]:
        found = search_code(
            snapshot_id, case["query"], limit=FULL_RANKING_LIMIT, table=config.CHUNK_TABLE
        )
        rank = next(
            (i for i, chunk in enumerate(found, start=1) if is_answer(chunk, case)), None
        )
        top = found[0] if found else None
        rows.append({
            "id": case["id"],
            "kind": case["kind"],
            "query": case["query"],
            "expected": expected_label(case),
            "rank": rank,
            "top_path": top["path"].split("/")[-1] if top else None,
            "top_distance": round(float(top["distance"]), 4) if top else None,
            # 어려운 질의는 결함과 구분해서 봐야 한다 — 순위가 낮아도 셋의 문제가 아니다.
            "difficulty": case.get("difficulty"),
        })

    # 입력 한도에 걸려 뒷부분이 잘린 청크 수.
    # 한도는 모델마다 다르므로(jina-code 8192, e5-large 512) 이름으로 짐작하지 않고
    # 토크나이저에서 읽는다. 그리고 **초과(>)가 아니라 도달(>=)**로 센다 —
    # 토크나이저가 이미 한도에서 잘라 돌려주므로 초과로 세면 영원히 0이다.
    truncated = None
    limit = embeddings.input_limit()
    if stats["token_counts"] is not None and limit:
        truncated = sum(1 for n in stats["token_counts"] if n >= limit)

    record = search_eval_log.append_eval(
        model=config.EMBEDDING_MODEL,
        dim=config.EMBEDDING_DIM,
        table=config.CHUNK_TABLE,
        repo="/".join(spec["repo"]),
        # 정답 조건이 다르면 다른 실험이다. 버전이 키에 없으면 옛 측정과 새 측정이
        # 비교 표의 한 칸에 겹쳐 하나가 사라진다(repo 키를 추가했을 때와 같은 문제).
        set_version=EVAL_SET_VERSION,
        rows=rows,
        total_chunks=stats["chunks"],
        index_ms=stats["index_ms"],
        peak_memory_mb=stats["peak_memory_mb"],
        truncated_chunks=truncated,
        # note 는 비교 표의 키에 들어간다 — 모델이 같아도 조건이 다르면 다른 실험이다.
        note=f"접두어 {config.EMBEDDING_QUERY_PREFIX or '없음'}",
    )

    with capsys.disabled():
        _print_report(record, stats)

    # 측정 자체가 목적이므로 품질을 단정하지 않는다. 다만 하네스가 깨진 경우는 잡는다.
    assert stats["chunks"] > 0, "청크가 하나도 없다 — 수집이나 청킹이 깨졌다"
    assert any(r["rank"] for r in rows), "정답을 하나도 못 찾았다 — 평가 하네스를 의심하라"


def _print_report(record: dict, stats: dict) -> None:
    s = record["summary"]
    print(f"\n{'=' * 78}")
    print(f"모델   {record['model']}  ({record['dim']}차원)")
    print(f"테이블 {record['table']}   {record['note']}")
    print(f"평가셋 {record['repo']}  v{record.get('set_version', 1)}"
          f"  (다른 버전과 수치를 비교하지 말 것)")
    print(f"청크   {s['total_chunks']}개 / 파일 {stats['files']}개")
    ms = record["index_ms"]
    print(
        f"인덱싱 수집 {ms['fetch']}ms · 청킹 {ms['chunk']}ms · "
        f"임베딩 {ms['embed']}ms · 저장 {ms['store']}ms   "
        f"피크메모리 {record['peak_memory_mb']}MB"
    )
    if record["truncated_chunks"] is not None:
        print(f"입력 한도 초과로 잘린 청크: {record['truncated_chunks']}개")
    print(f"{'-' * 78}")
    print(f"{'id':6} {'종류':10} {'순위':>5}  질의")
    for r in record["queries"]:
        rank = r["rank"] if r["rank"] else "없음"
        # 어려운 질의는 결함과 구분해서 읽어야 한다 — 순위가 낮아도 셋의 문제가 아니다.
        hard = "  [hard]" if r.get("difficulty") == "hard" else ""
        print(f"{r['id']:6} {r['kind']:10} {str(rank):>5}  {r['query']}{hard}")
    print(f"{'-' * 78}")
    for label, data in [("전체", s), *record["by_kind"].items()]:
        if not data:
            continue
        print(
            f"{label:10} MRR {data['mrr']:.4f}  "
            f"Recall@8 {data['recall_at_8']:.2f}  Recall@3 {data['recall_at_3']:.2f}  "
            f"평균순위 {data['mean_rank']}  ({data['found']}/{data['total']} 찾음)"
        )
    print(f"{'=' * 78}\n")
