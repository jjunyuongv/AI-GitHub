"""답변 품질 하네스의 **채점 함수**를 잰다. LLM 을 부르지 않는다 (무과금).

하네스 본체(`test_citation_quality.py`)는 `-m billed` 로만 도는데, 채점이 틀렸는지는
그때 알면 늦다 — 과금된 측정 한 판을 통째로 버리게 된다. 그래서 채점 함수만 떼어
`-m` 없이 매번 돌린다. 가짜 답변을 넣어 양방향을 다 확인한다.

`test_citation_quality` 는 모듈 전체에 billed 마커가 걸려 있지만, **import 는 과금이
아니다** — 마커는 수집된 테스트를 거를 뿐이고 이 파일은 함수만 꺼내 쓴다.
"""

import pytest

from app.services.claude_client import NO_BASIS_PHRASE, NOT_IN_SEARCH_PHRASE
from tests.search_eval_dataset import ABSENT_SETS, EVAL_SETS
from tests.test_citation_quality import _cited, _refused, _score, _summarize

# 정답이 있는 질의와 없는 질의. 하네스가 받는 것과 같은 모양이다.
ANSWERABLE = {
    "id": "x_01", "kind": "korean", "query": "비밀번호는 어떻게 암호화해?",
    "answers": [{"path_suffix": "SecurityConfig.java", "must_contain": "BCrypt"}],
}
ABSENT = {
    "id": "x_ab_01", "kind": "absent", "query": "휴가 신청 기능이 있어?",
    "why_absent": "vacation·휴가·leave 0회",
}

REFUSAL_ANSWER = f"{NO_BASIS_PHRASE}. 파일 목록에서는 관련 위치가 보이지 않습니다."
CITING_ANSWER = "SecurityConfig.java 의 26-91행에서 BCryptPasswordEncoder 를 만듭니다."


# ── 두 자는 서로 반대 방향이다 ────────────────────────────────

def test_refusal_answer_counts_as_refused_but_not_cited():
    assert _refused(REFUSAL_ANSWER)
    assert not _cited(REFUSAL_ANSWER, ANSWERABLE)


def test_citing_answer_counts_as_cited_but_not_refused():
    assert _cited(CITING_ANSWER, ANSWERABLE)
    assert not _refused(CITING_ANSWER)


def test_the_other_refusal_phrase_also_counts():
    """RAG 경로는 두 번째 문구를 쓴다. 하나만 보면 그 경로가 통째로 0점이 된다."""
    assert _refused(f"{NOT_IN_SEARCH_PHRASE}. UserController.java 근처일 수 있습니다.")


def test_a_plain_wrong_answer_is_neither():
    """지어낸 답변 — 거절도 안 했고 정답도 못 짚었다. 두 자 모두 실패로 센다."""
    answer = "VacationController.java 의 12행에서 휴가 신청을 처리합니다."

    assert not _refused(answer)
    assert not _cited(answer, ABSENT)


# ── 거절 질의를 기존 목록에 섞으면 안 되는 이유 ──────────────

def test_cited_is_always_false_without_answers():
    """`answers` 가 없는 질의는 _cited() 에서 **무조건 False** 다.

    거절 질의를 EVAL_QUERIES 에 섞으면 이 False 들이 인용 정확도의 분자에서 빠진 채
    분모만 늘린다 — 지표가 조용히 희석되고, 그 하락이 개선 실패로 오독된다.
    그래서 ABSENT_SETS 를 따로 둔다.
    """
    assert not _cited(REFUSAL_ANSWER, ABSENT)
    assert not _cited(CITING_ANSWER, ABSENT)
    assert not _cited("SecurityConfig.java 를 보세요", {"id": "x", "kind": "absent"})


def test_score_picks_the_ruler_by_kind():
    assert _score(REFUSAL_ANSWER, ABSENT)
    assert not _score(CITING_ANSWER, ABSENT)
    assert _score(CITING_ANSWER, ANSWERABLE)
    assert not _score(REFUSAL_ANSWER, ANSWERABLE)


# ── 집계 ──────────────────────────────────────────────────────

def _row(kind: str, ok: bool) -> dict:
    return {
        "kind": kind, "ok": ok, "cost_usd": 0.01, "llm_ms": 1000,
        "cache_write_tokens": 0, "cache_read_tokens": 0,
    }


def test_absent_rows_stay_out_of_citation_accuracy():
    """거절 질의가 인용 정확도의 모수에 들어가면 지난 기록과 비교가 끊긴다."""
    rows = [_row("korean", True), _row("identifier", True), _row("absent", False)]

    summary = _summarize(rows)

    assert summary["citation_accuracy"] == 1.0  # 2/2 — absent 행은 빠진다
    assert summary["refusal_accuracy"] == 0.0  # 0/1


def test_answerable_rows_stay_out_of_refusal_accuracy():
    rows = [_row("korean", False), _row("absent", True), _row("absent", False)]

    summary = _summarize(rows)

    assert summary["citation_accuracy"] == 0.0
    assert summary["refusal_accuracy"] == 0.5


def test_per_question_cost_and_latency_cover_every_row():
    """판정 기준 C 가 보는 값이다. 모수가 전체 행이 아니면 팔끼리 비교가 어긋난다."""
    rows = [_row("korean", True), _row("absent", True)]

    summary = _summarize(rows)

    assert summary["avg_cost_usd"] == 0.01
    assert summary["avg_llm_ms"] == 1000


def test_summarize_survives_a_set_without_absent_rows():
    """옛 모양(거절 질의 없음)으로도 죽지 않아야 한다 — 0으로 나누지 않는다."""
    summary = _summarize([_row("korean", True)])

    assert summary["refusal_accuracy"] == 0.0


# ── 거절 질의 목록 자체 ───────────────────────────────────────

def test_absent_sets_cover_every_eval_set():
    assert set(ABSENT_SETS) == set(EVAL_SETS)


def test_absent_rows_are_well_formed():
    """kind 가 틀리면 _score() 가 엉뚱한 자를 대고, why_absent 가 없으면 나중에
    "정말 없는 게 맞나"를 다시 확인할 수 없다."""
    for set_name, cases in ABSENT_SETS.items():
        assert len(cases) == 6, f"{set_name}: 거절 질의가 {len(cases)}개"
        for case in cases:
            assert case["kind"] == "absent", case["id"]
            assert "answers" not in case, case["id"]
            assert case["query"].strip(), case["id"]
            assert case["why_absent"].strip(), case["id"]


def test_query_ids_are_unique_across_every_set():
    """id 가 겹치면 하네스의 by_id 조회가 다른 질의의 결과를 집어 온다."""
    ids = [
        case["id"]
        for spec in EVAL_SETS.values()
        for case in spec["queries"]
    ] + [case["id"] for cases in ABSENT_SETS.values() for case in cases]

    duplicates = {i for i in ids if ids.count(i) > 1}

    assert not duplicates, f"중복된 질의 id: {sorted(duplicates)}"


@pytest.mark.parametrize("set_name", list(EVAL_SETS))
def test_absent_queries_are_not_mixed_into_the_search_eval_set(set_name):
    """섞이면 Recall@8 의 분모가 바뀌어 search_evals.jsonl 의 기존 기록과 끊긴다."""
    kinds = {case["kind"] for case in EVAL_SETS[set_name]["queries"]}

    assert "absent" not in kinds
