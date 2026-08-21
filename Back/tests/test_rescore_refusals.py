"""저장된 답변을 새 채점기로 **다시 매긴다**. 과금되지 않는다.

    pytest -m evaluation tests/test_rescore_refusals.py -s

`citation_evals.jsonl` 에 답변 원문이 그대로 남아 있으므로, 채점기를 고쳐도 89회를
다시 부를 이유가 없다. API 호출 0회 · $0 로 새 기준선이 나온다.
(`test_line_accuracy.py` 가 같은 자산을 같은 방식으로 재사용한다)

## 여기서 재는 것

옛 채점기는 규정 문구를 연속 문자열로 찾아 거절 24건 중 15건을 놓쳤다. 답변을 전부
읽어 보니 **날조는 0건이었고 전부 문구 변형이었다** — 자의 문제였지 모델의 문제가
아니었다. 새 채점기가 그 15건을 잡으면서도 **정답을 짚은 답변까지 거절로 끌고 오지는
않는지**를 여기서 본다. 뒤쪽이 진짜 방어선이다.

## 인용 정확도는 다시 매기지 않는다

`_cited()` 를 고치지 않았으므로 그 축은 옛 기준선과 그대로 비교된다. 바뀐 것은
거절 축뿐이다.
"""

import json
from pathlib import Path

import pytest

from tests.test_citation_quality import _cited, _first_sentence, _rate, _refused
from tests.search_eval_dataset import ABSENT_SETS, EVAL_SETS

pytestmark = pytest.mark.evaluation

CITATION_LOG = Path(__file__).resolve().parents[1] / "logs" / "citation_evals.jsonl"

# 옛 채점기로 잰 기준선 (2026-08-21). 재채점 결과를 이것과 나란히 놓는다.
OLD_BASELINE = {
    ("air", "rag"): {"citation": 0.7059, "refusal": 0.6667},
    ("marryday", "rag"): {"citation": 0.6875, "refusal": 0.6667},
    ("apns4j", "rag"): {"citation": 0.7500, "refusal": 0.0},
    ("apns4j", "full"): {"citation": 0.9375, "refusal": 0.1667},
}


def _rows() -> list[dict]:
    """이번 평가셋으로 잰 기록의 모든 행. 옛 기록(거절 질의 이전)은 건너뛴다."""
    if not CITATION_LOG.exists():
        pytest.skip(
            "citation_evals.jsonl 이 없습니다."
            ' 먼저 `pytest -m "billed and evaluation" tests/test_citation_quality.py` 를 돌리세요.'
        )
    records = [
        json.loads(line)
        for line in CITATION_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = []
    for rec in records:
        if "absent_set_version" not in rec:
            continue  # 거절 질의가 없던 시절의 기록
        for arm in rec["arms"]:
            for row in rec[arm]["rows"]:
                case = _case_for(rec["set"], row["id"])
                rows.append({**row, "set": rec["set"], "arm": arm, "case": case})
    if not rows:
        pytest.skip("거절 질의를 포함한 측정 기록이 아직 없습니다.")
    return rows


def _case_for(set_name: str, query_id: str) -> dict:
    pool = [*EVAL_SETS[set_name]["queries"], *ABSENT_SETS[set_name]]
    return next(c for c in pool if c["id"] == query_id)


# ── 자를 양쪽에서 조인다 ──────────────────────────────────────

def test_every_absent_answer_is_now_scored_as_refused():
    """거절 질의의 답변은 전부 거절로 잡혀야 한다.

    사람이 24건을 전부 읽고 "정확한 거절" 로 판정했다(날조 0건). 옛 채점기가 15건을
    놓친 것은 모델이 규정 문구에 낱말을 끼워 넣었기 때문이다.
    """
    missed = [
        f"  [{r['set']}/{r['arm']}] {r['id']}: {_first_sentence(r['answer'])[:90]}"
        for r in _rows()
        if r["kind"] == "absent" and not _refused(r["answer"])
    ]

    assert not missed, (
        f"거절인데 못 잡은 답변 {len(missed)}건:\n" + "\n".join(missed)
    )


def test_a_correct_citation_is_never_scored_as_a_refusal():
    """**진짜 방어선이다.** 정답 파일을 짚은 답변이 거절로도 잡히면 안 된다.

    느슨하게 할수록 이쪽이 터진다. 둘 다 참인 답변을 허용하면 "지어낸 답 + 면피 한 줄"
    이 거절로 통과해 축이 무의미해진다 — 거절 정확도가 잰다고 주장하는 것이
    정확히 그것이다.

    **정답을 못 짚은 답변까지 거절 0건을 요구하지는 않는다.** 그건 채점기를 틀리게
    만드는 요구다 — 검색이 못 찾아 모델이 실제로 거절한 경우가 있고(ko_04·py_id_05 등),
    그것을 "거절이 아니다" 라고 재는 자가 오히려 고장 난 자다.
    """
    both = [
        f"  [{r['set']}/{r['arm']}] {r['id']}: {_first_sentence(r['answer'])[:90]}"
        for r in _rows()
        if _cited(r["answer"], r["case"]) and _refused(r["answer"])
    ]

    assert not both, (
        f"정답을 짚었는데 거절로도 잡힌 답변 {len(both)}건 — 채점기가 너무 느슨하다:\n"
        + "\n".join(both)
    )


def test_refusal_detection_reads_only_the_opening_sentence():
    """첫 문장만 보는 것이 위 두 조건을 동시에 만족시키는 조임쇠다.

    본문 어디든 보면 근거를 대고 나서 덧붙인 단서까지 거절로 잡힌다.
    실측에서 그런 답변이 여러 건 있었다(ap_id_03·id_02·ap_ko_06).
    """
    qualified = (
        "ApnsPayload.java 의 30행에서 `class ApnsPayload extends Payload` 로 상속합니다."
        " 검색된 범위 안에서는 Payload 를 상속하는 다른 클래스는 확인되지 않습니다."
    )

    assert not _refused(qualified)
    assert _refused("검색된 범위 안에서는 그런 코드를 찾을 수 없습니다. 파일 목록을 보세요.")


# ── 새 기준선 ────────────────────────────────────────────────

def test_report_the_rescored_baseline(capsys):
    """새 기준선을 출력한다. 단정하지 않고 보고만 한다."""
    rows = _rows()
    keys = sorted({(r["set"], r["arm"]) for r in rows}, key=lambda k: (k[0], k[1]))

    with capsys.disabled():
        print(f"\n저장된 답변 {len(rows)}건을 다시 매긴다 (LLM 호출 없음 · $0)")
        print("\n" + "=" * 76)
        print(f"{'세트/팔':<18}{'인용':>18}{'거절 (옛 → 새)':>28}")
        print("=" * 76)
        for set_name, arm in keys:
            subset = [r for r in rows if r["set"] == set_name and r["arm"] == arm]
            absent = [r for r in subset if r["kind"] == "absent"]
            answerable = [r for r in subset if r["kind"] != "absent"]
            new_refusal = _rate([{"ok": _refused(r["answer"])} for r in absent])
            new_citation = _rate(
                [{"ok": _cited(r["answer"], r["case"])} for r in answerable]
            )
            old = OLD_BASELINE.get((set_name, arm), {})
            drift = "" if old.get("citation") == new_citation else "  ← 인용이 달라졌다"
            print(f"{set_name + '/' + arm:<18}{new_citation:>18}"
                  f"{str(old.get('refusal')) + ' → ' + str(new_refusal):>28}{drift}")
        print("=" * 76)
        print("인용 정확도는 _cited() 를 안 고쳤으므로 옛 기준선과 그대로 비교된다.")
        print("**거절 축만 자가 바뀌었다 — 옛 수치와 비교하지 말 것.**")
        print("apns4j/rag 의 옛 0.0 은 바닥 효과였다. 1단계에서 이 숫자가 오르면")
        print("tool use 의 성과가 아니라 자를 고친 결과다.\n")

    assert rows
