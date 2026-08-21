"""인용 정확도 — RAG 경로와 전체 주입 경로를 **같은 자로** 비교한다.

**과금된다.** 질의마다 Claude 를 실제로 부른다. `-m billed` 를 명시했을 때만 돈다:

    pytest -m billed tests/test_citation_quality.py -s

## 왜 순위 지표를 안 쓰는가

Recall@8·MRR 은 검색 순위 지표인데 전체 주입에는 검색이 없다. 형식상 Recall@∞ = 1.0 이
되어 자동으로 만점이다 — 그 숫자를 "전체 주입이 이겼다"로 읽으면 안 된다.

대신 **답변이 정답 파일을 실제로 짚었는지**를 센다. 평가셋의 `answers[].path_suffix` 를
답변 텍스트에서 찾는 문자열 매칭이라 **LLM 심판이 필요 없고 결정적이다.**
`CHAT_SYSTEM_PROMPT` 가 "어느 파일 몇 행인지 밝히라"고 이미 강제하고 있어 형식도 맞는다.

## 판정 기준 (측정 전에 고정한다)

전체 주입이 **떨어지면 우회를 접는다.** 동률이면 RAG 유지(비용·지연이 낮다).
**올라야만** 우회를 켠다. 이 기준을 결과를 보고 정하면 측정이 아니라 사후 합리화가 된다.
"큰 덩어리에 섞이면 초점이 흐려진다"는 실패 방식이 이 저장소에 이미 기록돼 있어
(plan.md, `py_ko_01` 1→10위) 전체 주입이 지는 결과는 실제로 가능하다.
"""

import json
import time
from pathlib import Path

import pytest

from app import config
from app.core import embeddings
from app.core.chunk_rule import rule_version
from app.core.chunker import chunk_files
from app.db import chunks as chunk_store
from app.db import index_status, pool
from app.services import claude_client
from app.services.context_builder import build_source_bundle
from app.services.indexer import format_snippets, search_code
from tests.search_eval_dataset import EVAL_SET_VERSION, EVAL_SETS
from tests.test_search_quality import _snapshot_for, _source_files

pytestmark = [pytest.mark.evaluation, pytest.mark.billed]

# 우회 검수 대상. 앞의 둘은 임계값을 넘어 이 비교가 성립하지 않는다.
SET_NAME = "apns4j"

LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "citation_evals.jsonl"

# 대화 이력 없이 질의 하나씩 독립으로 묻는다 — 앞 질문의 답이 다음 답에 섞이면
# 두 경로의 차이가 아니라 대화 순서의 차이를 재게 된다.
NO_HISTORY: list[dict] = []


def _cited(answer: str, case: dict) -> bool:
    """답변이 정답 파일을 짚었는가. answers 중 하나라도 맞으면 정답이다."""
    return any(a["path_suffix"] in answer for a in case["answers"])


def _ensure_index(snapshot_id: int, repo: tuple[str, str], files: dict) -> None:
    """RAG 경로가 쓸 검색 색인. 이미 완료돼 있으면 그대로 쓴다."""
    if index_status.active_build_id(snapshot_id, table=config.CHUNK_TABLE):
        return
    pieces = chunk_files(
        files, count_tokens=embeddings.count_tokens, token_limit=embeddings.input_limit()
    )
    vectors = embeddings.embed_documents([p["content"] for p in pieces])
    build_id = index_status.begin(
        snapshot_id, table=config.CHUNK_TABLE, chunk_rule=rule_version()
    )
    if build_id is None:
        index_status.reset_running()
        build_id = index_status.begin(
            snapshot_id, table=config.CHUNK_TABLE, chunk_rule=rule_version()
        )
    saved = chunk_store.insert_chunks(
        build_id, snapshot_id, pieces, vectors, table=config.CHUNK_TABLE
    )
    index_status.complete(build_id, saved)
    index_status.prune_builds(snapshot_id, table=config.CHUNK_TABLE)


def _ask(context: str, summary: str, case: dict, *, snippets: str, bundle: str) -> dict:
    result = claude_client.run_chat(
        context=context,
        summary=summary,
        history=NO_HISTORY,
        question=case["query"],
        snippets=snippets,
        source_bundle=bundle,
    )
    return {
        "id": case["id"],
        "kind": case["kind"],
        "cited": _cited(result["text"], case),
        "answer": result["text"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "cache_write_tokens": result["cache_write_tokens"],
        "cache_read_tokens": result["cache_read_tokens"],
        "cost_usd": result["cost_usd"] or 0.0,
    }


def _summarize(rows: list[dict]) -> dict:
    def rate(kind: str | None) -> float:
        subset = [r for r in rows if kind is None or r["kind"] == kind]
        return round(sum(r["cited"] for r in subset) / len(subset), 4) if subset else 0.0

    return {
        "citation_accuracy": rate(None),
        "korean": rate("korean"),
        "identifier": rate("identifier"),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
        "cache_write_tokens": sum(r["cache_write_tokens"] for r in rows),
        "cache_read_tokens": sum(r["cache_read_tokens"] for r in rows),
    }


def test_compare_citation_accuracy(capsys):
    if not pool.is_enabled():
        pytest.skip("DATABASE_URL 이 없어 인용 정확도 측정을 건너뜁니다.")
    if not config.ANTHROPIC_API_KEY:
        pytest.skip("ANTHROPIC_API_KEY 가 없어 인용 정확도 측정을 건너뜁니다.")

    spec = EVAL_SETS[SET_NAME]
    repo = spec["repo"]
    files = _source_files(repo)
    snapshot_id = _snapshot_for(repo)
    _ensure_index(snapshot_id, repo, files)

    bundle = build_source_bundle(files)
    context = f"## 레포지토리 정보\n- 이름: {repo[0]}/{repo[1]}"
    summary = "APNs 푸시 알림을 보내는 Java 라이브러리입니다."

    started = time.perf_counter()
    results: dict[str, list[dict]] = {}
    for path_name in ("rag", "full"):
        rows = []
        for case in spec["queries"]:
            snippets = ""
            if path_name == "rag":
                snippets = format_snippets(
                    search_code(snapshot_id, case["query"], table=config.CHUNK_TABLE)
                )
            rows.append(
                _ask(
                    context, summary, case,
                    snippets=snippets,
                    bundle=bundle if path_name == "full" else "",
                )
            )
        results[path_name] = rows

    rag, full = _summarize(results["rag"]), _summarize(results["full"])

    print(f"\n{repo[0]}/{repo[1]} — 질의 {len(spec['queries'])}개 · "
          f"{int(time.perf_counter() - started)}초 · 번들 {len(bundle):,}자")
    print(f"\n{'지표':<16} {'RAG':>10} {'전체주입':>10}")
    for label, key in (
        ("인용 정확도", "citation_accuracy"),
        ("  한국어", "korean"),
        ("  식별자", "identifier"),
        ("비용(USD)", "cost_usd"),
    ):
        print(f"{label:<16} {rag[key]:>10} {full[key]:>10}")

    print(f"\n{'id':<10} {'종류':<11} {'RAG':>5} {'전체':>5}  질의")
    by_id = {r["id"]: r for r in results["full"]}
    for r in results["rag"]:
        f = by_id[r["id"]]
        mark = "" if r["cited"] == f["cited"] else ("  ← 전체주입 우세" if f["cited"] else "  ← RAG 우세")
        case = next(c for c in spec["queries"] if c["id"] == r["id"])
        print(f"{r['id']:<10} {r['kind']:<11} {'O' if r['cited'] else 'X':>5} "
              f"{'O' if f['cited'] else 'X':>5}  {case['query']}{mark}")

    verdict = (
        "전체 주입을 켠다" if full["citation_accuracy"] > rag["citation_accuracy"]
        else "RAG 를 유지한다"
    )
    print(f"\n판정: {verdict} "
          f"(기준: 올라야만 켠다. 동률·하락이면 유지)")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "repo": f"{repo[0]}/{repo[1]}",
            "set_version": EVAL_SET_VERSION,
            "model": claude_client.DEFAULT_MODEL,
            "bundle_chars": len(bundle),
            "rag": {**rag, "rows": results["rag"]},
            "full": {**full, "rows": results["full"]},
        }, ensure_ascii=False) + "\n")

    # 단정하지 않는다 — 측정이다. 판정은 위 출력과 기록으로 사람이 한다.
    assert results["rag"] and results["full"]
