"""답변이 밝힌 **행 번호가 맞는가**.

`-m evaluation` 으로만 돈다. **과금되지 않는다** — 이미 받아 둔 답변을 다시 읽을 뿐이다:

    pytest -m evaluation tests/test_line_accuracy.py -s

## 왜 필요한가

화면 확인에서 모델이 `this.size = (executorSize > processors) ? ...` 를 35행이라 했는데
실제로는 48행이었다(35행은 같은 이름의 필드 선언이다). 번들이 틀린 번호를 실었을
가능성은 그때 배제했다 — 2,340줄을 원문과 대조해 불일치 0건이었다. **모델이 옳은
번호를 받고도 틀린 줄을 짚은 것이다.**

그때 관찰이 3건뿐이라 "얼마나 자주 틀리는가"를 몰랐다. `citation_evals.jsonl` 에
답변 전문이 남아 있으므로 그걸 다시 읽어 빈도를 센다.

## 판정 방법과 그 한계

답변에서 `코드 조각 + 행 번호`를 뽑아, 그 조각이 소스의 그 범위 안에 실제로 있는지 본다.
문자열 대조라 결정적이고 LLM 심판이 필요 없다.

**한계를 분명히 해 둔다.** 자연어를 정규식으로 뽑는 것이라:
- **코드를 그대로 인용한 것만 판정한다**(`CODE_LIKE`). 이름 하나만 적은 것은 그 줄에
  그 문자열이 있다는 주장이 아니라 서술이므로, 채점하면 파서의 오탐을 재게 된다
- 답변이 코드를 의역했거나 조각이 소스에 없으면 **판정하지 않는다**(모수에서 뺀다)
- 같은 조각이 여러 곳에 있으면 **하나라도 범위에 들면 맞다고 본다**(관대한 쪽)
따라서 이 수치는 정확도의 하한이 아니라 **대략적 빈도**다. 추세를 보는 용도다.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from app.services.citations import extract as _citations
from app.services.citations import resolve_path

pytestmark = pytest.mark.evaluation

BACK_DIR = Path(__file__).resolve().parents[1]
CITATION_LOG = BACK_DIR / "logs" / "citation_evals.jsonl"
SOURCE_CACHE_DIR = BACK_DIR / "cache" / "eval_sources"

# **추출 규칙은 `app/services/citations.py` 에 있다.** 여기 두면 파서가 둘이 된다 —
# 화면이 링크로 뜨는 인용과 이 하네스가 채점하는 인용이 다른 집합이 되고, 한쪽만
# 고치면 조용히 어긋난다. 여기 남는 것은 **판정**(`_verdict`)뿐이다.


def _source_for(answer_path: str, files: dict[str, str]) -> str | None:
    """답변이 말한 경로에 해당하는 소스. 경로 해석은 공유 모듈이 한다."""
    path = resolve_path(answer_path, list(files))
    return files[path] if path else None


def _verdict(cite: dict, files: dict[str, str]) -> tuple[str, str | None]:
    """('correct'|'wrong'|'unknown', 설명). 소스에 없는 조각은 판정하지 않는다."""
    source = _source_for(cite["file"], files)
    if source is None:
        return "unknown", None
    lines = source.splitlines()

    for snippet in cite["snippets"]:
        needle = snippet.strip()
        found = [i for i, text in enumerate(lines, start=1) if needle in text]
        if not found:
            continue  # 의역했거나 우리가 잘못 뽑은 것 — 다음 조각을 본다
        if any(cite["start"] <= n <= cite["end"] for n in found):
            return "correct", None
        return "wrong", (
            f"{cite['file']} {cite['start']}~{cite['end']}행이라 했으나"
            f" `{needle[:40]}` 은 실제 {found[:3]}행"
        )
    return "unknown", None


def test_measure_line_number_accuracy(capsys):
    """저장된 답변에서 행 번호 인용의 정확도를 센다. 단정하지 않고 측정만 한다."""
    if not CITATION_LOG.exists():
        pytest.skip(
            "citation_evals.jsonl 이 없습니다."
            " 먼저 `pytest -m billed tests/test_citation_quality.py` 를 돌리세요."
        )

    records = [
        json.loads(line)
        for line in CITATION_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    with capsys.disabled():
        print(f"\n기록 {len(records)}건 — 저장된 답변을 다시 읽는다 (LLM 호출 없음)")
        total = Counter()
        wrongs = []

        for rec in records:
            owner, name = rec["repo"].split("/")
            cache = SOURCE_CACHE_DIR / f"{owner}__{name}.json".lower()
            if not cache.exists():
                print(f"  {rec['repo']}: 소스 캐시가 없어 건너뜁니다")
                continue
            files = json.loads(cache.read_text(encoding="utf-8"))

            # 어느 팔이 돌았는지는 기록마다 다르다 — 전체 주입 임계값을 넘는 저장소는
            # RAG 한 팔만 돈다. 옛 기록에는 이 키가 없어 두 팔로 폴백한다.
            for path_name in rec.get("arms", ("rag", "full")):
                counts = Counter()
                for row in rec[path_name]["rows"]:
                    for cite in _citations(row.get("answer", "")):
                        verdict, detail = _verdict(cite, files)
                        counts[verdict] += 1
                        total[verdict] += 1
                        if verdict == "wrong":
                            wrongs.append(f"[{path_name} {row['id']}] {detail}")
                judged = counts["correct"] + counts["wrong"]
                rate = counts["correct"] / judged if judged else 0.0
                print(f"  {rec['repo']} {path_name:5} 판정 {judged}건 중 정확 "
                      f"{counts['correct']}건 ({rate:.0%}) · 판정불가 {counts['unknown']}")

        judged = total["correct"] + total["wrong"]
        print(f"\n{'=' * 70}")
        if judged:
            print(f"행 번호 정확도 **{total['correct'] / judged:.1%}** "
                  f"({total['correct']}/{judged}) · 판정불가 {total['unknown']}건")
        print("판정불가 = 인용한 조각이 소스에 그대로 없는 경우(의역 등). 모수에서 뺀다.")
        if wrongs:
            print(f"\n틀린 인용 {len(wrongs)}건:")
            for w in wrongs[:20]:
                print(f"  {w}")
        print(f"{'=' * 70}\n")

    assert records, "기록이 비어 있다"
