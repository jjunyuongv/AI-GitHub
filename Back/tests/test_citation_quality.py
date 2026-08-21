"""답변 품질 — 인용 정확도와 거절 정확도를 **같은 자로** 잰다.

**과금된다.** 질의마다 Claude 를 실제로 부른다. 두 마커를 **다** 명시했을 때만 돈다:

    pytest -m "billed and evaluation" tests/test_citation_quality.py -s

`-m billed` 만 쓰면 **조용히 3건 skip 된다.** conftest 의 opt-in 게이트는 마커마다
따로 물어서, 이 모듈이 단 `evaluation` 마커가 `-m` 에 없으면 그것만으로 건너뛴다.
0.9초에 `sss` 로 끝나면 측정이 아니라 아무것도 안 돈 것이다 — 로그 파일도 안 생긴다.

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

## 답변 품질 판정 기준 — tool use 도입용 (측정 전에 고정한다)

위 기준은 "전체 주입 우회를 켤 것인가"의 자다. 아래는 **tool use 를 붙일 것인가**의 자다.

    A. 인용 정확도가 기준선보다 떨어지면 기각.
    B. A 가 동률이면 거절 정확도를 본다. 떨어지면 기각.
    C. A·거절이 올라도 질문당 비용이 기준선의 COST_RATIO_LIMIT 배를 넘으면
       전면 도입하지 않고 "큰 저장소 전용"으로만 켠다.

### 왜 거절 축이 따로 필요한가

검색을 반복하는 경로는 계속 뒤지다 지어낼 여지가, 한 번 검색하고 끝내는 경로보다 크다.
그런데 인용 정확도는 **정답이 있는 질의**에서만 재므로 그 실패를 못 잡는다 —
정답이 없는 질의에서는 짚을 파일이 없어 **날조와 침묵이 똑같이 0점**으로 보인다.
정답이 없는 질의(`ABSENT_SETS`)를 따로 두고 "규정대로 거절했는가"를 세야 차이가 드러난다.

### 이 자의 한계 — 알고 쓴다

문구 매칭이라 "KeyStoreGetter 는 읽어 오기만 하고 만료 검사는 없습니다"처럼 **내용은
맞는데 규정 문구를 안 쓴 답변**은 실패로 센다. 재는 것은 정확히 "규정대로 거절했는가"이고,
"지어내지 않았는가"의 대리 지표다. 두 경로에 같은 자를 대므로 **비교**에는 쓸 수 있지만,
절대값을 "이만큼 지어낸다"로 읽으면 안 된다.
"""

import json
import re
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
from app.services.indexer import format_snippets, measure_bundle, search_code
from tests.search_eval_dataset import (
    ABSENT_SET_VERSION,
    ABSENT_SETS,
    EVAL_SET_VERSION,
    EVAL_SETS,
)
from tests.test_search_quality import _snapshot_for, _source_files

pytestmark = [pytest.mark.evaluation, pytest.mark.billed]

LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "citation_evals.jsonl"

# 질문당 비용이 기준선의 몇 배를 넘으면 전면 도입을 접는가 (위 판정 기준 C).
# 3배는 "큰 저장소에서만 켜면 되는" 구간의 하한으로 잡은 값이다 — 임의의 저장소를
# 받는 서비스라 평균 질문 하나의 값이 세 배가 되면 우회 판정과 같은 층위의 결정이 된다.
COST_RATIO_LIMIT = 3.0

# 대화의 두 번째 메시지로 넣을 요약. 실제 서비스에서는 LLM 이 만든 요약이 여기 온다.
# 세트마다 고정 문장을 쓴다 — 매번 요약을 새로 만들면 그 편차가 두 경로의 차이에 섞인다.
# (평가셋이 아니라 **대화 하네스의 입력**이라 search_eval_dataset 에 두지 않는다)
SET_SUMMARIES = {
    "air": "사내 그룹웨어입니다. 전자결재·일정·채팅·보고서를 다루는 Spring Boot 애플리케이션입니다.",
    "marryday": "웨딩드레스 가상 피팅 서비스입니다. FastAPI 백엔드와 React 프론트로 이루어져 있습니다.",
    "apns4j": "APNs 푸시 알림을 보내는 Java 라이브러리입니다.",
}

ARM_LABELS = {"rag": "RAG", "full": "전체주입"}

# 대화 이력 없이 질의 하나씩 독립으로 묻는다 — 앞 질문의 답이 다음 답에 섞이면
# 두 경로의 차이가 아니라 대화 순서의 차이를 재게 된다.
NO_HISTORY: list[dict] = []


def _cited(answer: str, case: dict) -> bool:
    """답변이 정답 파일을 짚었는가. answers 중 하나라도 맞으면 정답이다.

    **정답이 없는 질의(kind="absent")를 넣으면 언제나 False 다.** answers 가 없어
    any([]) 가 되기 때문이다. 그래서 거절 질의를 기존 목록에 섞으면 안 된다 —
    섞으면 인용 정확도가 조용히 희석되고, 그 하락이 개선 실패로 오독된다.
    """
    return any(a["path_suffix"] in answer for a in case.get("answers", []))


# ── 거절 채점기 ──────────────────────────────────────────────
#
# **문장 구조에서 유도했다. 정규식을 늘려 15건을 맞춘 것이 아니다.**
# 거절 문장은 예외 없이 "[어디를 봤는가] + [거기에 없다]" 두 조각으로 이루어진다.
# 그래서 두 조각을 따로 정의하고, 한 문장 안에서 이 순서로 나타나는지만 본다.
#
# 옛 채점기는 규정 문구 두 개를 **연속 문자열**로 찾았는데, 모델은 거의 항상
# "검색된 `코드` 범위에는 … 없습니다" 처럼 낱말을 끼워 넣어서 24건 중 15건이
# 새어 나갔다(2026-08-21 기준선). 날조는 0건이었다 — 자의 문제였다.
#
# CHAT_SYSTEM_PROMPT 는 건드리지 않는다. 프롬프트를 고치면 재는 대상이 바뀌어
# 인용 정확도까지 흔들리고 89회를 다시 돌려야 한다. 여기는 채점기만 고친다.

# (가) 어디를 봤는가. 답변이 근거의 범위를 가리키는 표현.
REFUSAL_SCOPES = (
    r"검색된",  # 검색된 범위 / 검색된 코드 / 검색된 코드 범위 / 검색된 부분
    r"검색\s*결과",
    r"(?:주어진|제공된)\s*(?:정보|코드|저장소|소스)",
    r"(?:저장소\s*)?전체\s*소스",  # 전체 주입 팔이 쓰는 계열
    r"코드\s*전체",
)

# (나) 거기에 없다. 부정 술어.
REFUSAL_NEGATIONS = (
    r"없(?:습니다|다|음|어요)",
    r"보이지\s*않",
    r"존재하지\s*않",
    r"찾을\s*수\s*없",
    r"확인되지\s*않",
    r"알\s*수\s*없",
    r"나타나지\s*않",
    r"포함되어\s*있지\s*않",
)

# (다) 양보 — "X 는 있지만 Y 는 없다". 이건 거절 선언이 아니라 **일부는 답한** 문장이다.
# 근거를 대고 나서 못 찾은 부분을 밝히는 것은 프롬프트가 시킨 대로 답한 것이다.
# 이걸 거절로 세면 "지어낸 답 + 면피 한 줄" 이 그대로 통과한다.
#
# **모호한 문장은 거절로 세지 않는다.** 거절을 적게 세는 쪽으로 틀리면 tool use 가
# 실제보다 정직해 보이는 일은 없다 — 안전한 방향이다.
REFUSAL_CONCESSIONS = (
    r"(?:보이|있|존재하|확인되|나오|나타나)(?:지만|으나|지마는)",
)

_REFUSAL_RE = re.compile(
    f"(?:{'|'.join(REFUSAL_SCOPES)}).*?(?:{'|'.join(REFUSAL_NEGATIONS)})"
)
_CONCESSION_RE = re.compile("|".join(REFUSAL_CONCESSIONS))

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _first_sentence(answer: str) -> str:
    return _SENTENCE_SPLIT.split(answer.strip(), maxsplit=1)[0] if answer.strip() else ""


def _refused(answer: str) -> bool:
    """답변이 **거절로 시작하는가.**

    **첫 문장만 본다.** 이것이 이 채점기에서 가장 중요한 조임쇠다.
    `CHAT_SYSTEM_PROMPT` 가 "근거가 없으면 … 한 문장으로 밝히고" 를 요구하므로,
    진짜 거절은 답변을 열면서 나온다. 실측에서도 거절 질의 24건 전부가 첫 문장에서
    거절했다.

    본문 어디든 보면 **근거를 대고 나서 덧붙인 단서**까지 거절로 잡힌다 —
    "ApnsPayload 가 Payload 를 상속합니다. 검색된 범위 안에서 상속하는 다른 클래스는
    확인되지 않습니다" 같은 답변은 거절이 아니라 정확한 답이다. 그걸 거절로 세면
    "지어낸 답 + 면피 한 줄" 이 거절로 통과해 축이 무의미해진다.

    두 팔 모두 세 계열을 다 인정한다. 전체 주입에서 "검색된 범위" 표현은 프롬프트
    위반이지만 그건 **형식 위반이지 날조가 아니다** — 이 축이 재려는 것은 지어냈는가다.
    """
    opening = _first_sentence(answer)
    if _CONCESSION_RE.search(opening):
        return False
    return bool(_REFUSAL_RE.search(opening))


def _score(answer: str, case: dict) -> bool:
    """이 답변이 이 질의에서 옳은가. 질의 종류에 따라 다른 자를 댄다."""
    if case["kind"] == "absent":
        return _refused(answer)
    return _cited(answer, case)


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
        "ok": _score(result["text"], case),
        "answer": result["text"],
        # 지연은 판정 기준 B·C 와 함께 보는 축이다. tool use 를 붙이면 검색을 여러 번
        # 도느라 여기가 가장 크게 움직인다 — 버리면 그 변화를 사후에 못 잰다.
        "llm_ms": result["llm_ms"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "cache_write_tokens": result["cache_write_tokens"],
        "cache_read_tokens": result["cache_read_tokens"],
        "cost_usd": result["cost_usd"] or 0.0,
    }


def _rate(rows: list[dict]) -> float:
    return round(sum(r["ok"] for r in rows) / len(rows), 4) if rows else 0.0


def _summarize(rows: list[dict]) -> dict:
    """팔 하나의 집계.

    **인용 정확도의 모수에서 absent 행을 뺀다.** 안 빼면 지난 기록(set_version=2,
    16질의)과 같은 칸에서 비교가 끊긴다 — 거절 질의를 더한 것이 인용 정확도를 떨어뜨린
    것처럼 보인다. `EVAL_SET_VERSION` 을 2 로 둔 이유가 이것이다.
    """
    answerable = [r for r in rows if r["kind"] != "absent"]
    absent = [r for r in rows if r["kind"] == "absent"]
    return {
        "citation_accuracy": _rate(answerable),
        "korean": _rate([r for r in rows if r["kind"] == "korean"]),
        "identifier": _rate([r for r in rows if r["kind"] == "identifier"]),
        "refusal_accuracy": _rate(absent),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
        "avg_cost_usd": round(sum(r["cost_usd"] for r in rows) / len(rows), 6),
        "avg_llm_ms": round(sum(r["llm_ms"] for r in rows) / len(rows)),
        "cache_write_tokens": sum(r["cache_write_tokens"] for r in rows),
        "cache_read_tokens": sum(r["cache_read_tokens"] for r in rows),
    }


def _arms_for(tokens: int) -> tuple[str, ...]:
    """이 저장소에서 성립하는 팔.

    **저장소 이름으로 가르지 않는다**(CLAUDE.md §7). 프로덕션이 우회를 판정할 때 쓰는
    바로 그 기준(번들 토큰 수 ≤ 임계값)을 그대로 쓴다 — 하네스와 서비스의 기준이
    갈리면 "여기서는 성립하는데 서비스에서는 안 켜지는" 비교를 하게 된다.
    임계값을 넘는 저장소에서 전체 주입은 아예 성립하지 않으므로 RAG 한 팔만 돈다.
    """
    if tokens and tokens <= config.FULL_INJECTION_MAX_TOKENS:
        return ("rag", "full")
    return ("rag",)


@pytest.mark.parametrize("set_name", list(EVAL_SETS))
def test_measure_answer_quality(set_name, capsys):
    """세트 하나를 성립하는 모든 팔로 돌려 인용·거절 정확도를 재고 기록한다.

    단정하지 않는다 — 측정이다. 판정은 위 docstring 의 기준으로 사람이 한다.
    """
    if not pool.is_enabled():
        pytest.skip("DATABASE_URL 이 없어 답변 품질 측정을 건너뜁니다.")
    if not config.ANTHROPIC_API_KEY:
        pytest.skip("ANTHROPIC_API_KEY 가 없어 답변 품질 측정을 건너뜁니다.")

    spec = EVAL_SETS[set_name]
    repo = spec["repo"]
    cases = [*spec["queries"], *ABSENT_SETS[set_name]]
    files = _source_files(repo)
    snapshot_id = _snapshot_for(repo)
    _ensure_index(snapshot_id, repo, files)

    # 무과금이다 — 토큰 계산 엔드포인트는 추론을 돌리지 않는다.
    bundle, bundle_tokens = measure_bundle(files)
    arms = _arms_for(bundle_tokens)
    context = f"## 레포지토리 정보\n- 이름: {repo[0]}/{repo[1]}"
    summary = SET_SUMMARIES[set_name]

    started = time.perf_counter()
    results: dict[str, list[dict]] = {}
    for arm in arms:
        rows = []
        for case in cases:
            snippets = ""
            if arm == "rag":
                snippets = format_snippets(
                    search_code(snapshot_id, case["query"], table=config.CHUNK_TABLE)
                )
            rows.append(
                _ask(
                    context, summary, case,
                    snippets=snippets,
                    bundle=bundle if arm == "full" else "",
                )
            )
        results[arm] = rows

    totals = {arm: _summarize(rows) for arm, rows in results.items()}

    with capsys.disabled():
        _print_report(set_name, repo, cases, arms, results, totals,
                      bundle, bundle_tokens, time.perf_counter() - started)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "repo": f"{repo[0]}/{repo[1]}",
        "set": set_name,
        "set_version": EVAL_SET_VERSION,
        "absent_set_version": ABSENT_SET_VERSION,
        "model": claude_client.DEFAULT_MODEL,
        "bundle_chars": len(bundle),
        "bundle_tokens": bundle_tokens,
        # 어느 팔이 돌았는지 기록에 남긴다. 옛 기록에는 이 키가 없으므로 읽는 쪽은
        # ("rag", "full") 로 폴백한다 (tests/test_line_accuracy.py).
        "arms": list(arms),
    }
    for arm in arms:
        record[arm] = {**totals[arm], "rows": results[arm]}
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 단정하지 않는다 — 측정이다. 다만 하네스가 깨진 경우는 잡는다.
    assert all(results[arm] for arm in arms)


def _print_report(set_name, repo, cases, arms, results, totals,
                  bundle, bundle_tokens, elapsed) -> None:
    """팔 개수에 맞춰 표를 그린다. 팔이 하나면 비교 열도 판정 줄도 뜨지 않는다."""
    labels = [ARM_LABELS[a] for a in arms]
    print(f"\n{repo[0]}/{repo[1]} [{set_name}] — 질의 {len(cases)}개 "
          f"(거절 {sum(1 for c in cases if c['kind'] == 'absent')}개) · "
          f"팔 {'·'.join(labels)} · {int(elapsed)}초")
    print(f"번들 {len(bundle):,}자 / {bundle_tokens:,}토큰 "
          f"(전체 주입 임계값 {config.FULL_INJECTION_MAX_TOKENS:,})")

    print("\n" + f"{'지표':<16}" + "".join(f"{label:>12}" for label in labels))
    for label, key in (
        ("인용 정확도", "citation_accuracy"),
        ("  한국어", "korean"),
        ("  식별자", "identifier"),
        ("거절 정확도", "refusal_accuracy"),
        ("비용(USD)", "cost_usd"),
        ("질문당 비용", "avg_cost_usd"),
        ("질문당 지연(ms)", "avg_llm_ms"),
    ):
        print(f"{label:<16}" + "".join(f"{totals[a][key]:>12}" for a in arms))

    print("\n" + f"{'id':<10} {'종류':<11}" + "".join(f"{lb:>7}" for lb in labels) + "  질의")
    by_id = {arm: {r["id"]: r for r in rows} for arm, rows in results.items()}
    for case in cases:
        marks = "".join(
            f"{'O' if by_id[a][case['id']]['ok'] else 'X':>7}" for a in arms
        )
        note = ""
        if len(arms) > 1:
            scores = [by_id[a][case["id"]]["ok"] for a in arms]
            if len(set(scores)) > 1:
                won = [ARM_LABELS[a] for a, ok in zip(arms, scores) if ok]
                note = f"  ← {'·'.join(won)} 우세"
        print(f"{case['id']:<10} {case['kind']:<11}{marks}  {case['query']}{note}")

    if len(arms) > 1:
        rag, full = totals["rag"], totals["full"]
        verdict = (
            "전체 주입을 켠다" if full["citation_accuracy"] > rag["citation_accuracy"]
            else "RAG 를 유지한다"
        )
        print(f"\n판정: {verdict} (기준: 올라야만 켠다. 동률·하락이면 유지)")
    else:
        print("\n이 저장소는 전체 주입 임계값을 넘어 우회 비교가 성립하지 않는다 "
              "— RAG 한 팔의 기준선만 남긴다.")
