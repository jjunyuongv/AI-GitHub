"""배치 크기 튜닝 — 지금 쓰는 모델에서 몇 개씩 넘기는 것이 가장 빠른가.

일반 테스트가 아니다. `-m evaluation` 을 붙였을 때만 돈다:

    pytest -m evaluation tests/test_embed_batch_size.py -s

**왜 따로 있는가.** `test_embed_speed.py` 는 **모델 둘을 고정 배치로** 비교한다.
이 하네스는 반대다 — **모델 하나를 배치 크기별로** 잰다. `EMBED_BATCH_SIZE` 는
모델을 바꿀 때마다 다시 정해야 하는 값인데(짧은 청크가 가장 긴 청크에 맞춰 패딩되는
낭비와, 배치가 작을 때의 호출 오버헤드가 맞바뀌는 지점이 모델마다 다르다),
그 지점을 찾는 도구가 없었다.

**측정 대상은 설정이 가리키는 모델이다.** 모델 이름을 여기 박지 않는다 —
`.env` 를 바꾸면 이 하네스도 그 모델을 잰다.

**이 하네스의 답을 그대로 믿고 상수를 바꾸지 말 것.** 청크 200개짜리 표본은 4,000개짜리
실제 색인을 예측하지 못한다. 2026-08-20 에 같은 저장소로 대조한 결과:

| 배치 | 이 하네스 (200청크) | 실제 재색인 (4,365청크) | 어긋남 |
|---|---:|---:|---:|
| 32 | 160.6ms/청크 | 129.4ms/청크 | 1.2배 (실제가 빠름) |
| 1 | 73.0ms/청크 | **246.5ms/청크** | **3.4배 (실제가 느림)** |

**그리고 이 기기에서는 실제 재색인으로도 답이 안 났다.** CPU 점유 7.7x → 6.6x (14% 차이)가
시간 1.84배를 만드는데, 그 변동이 배치 차이보다 커서 결론이 세 번 뒤집혔다. 같은 CPU
수준에서 견주면 배치 32 와 1 의 차이는 3.5% 로 노이즈였다.

**그래서 이 하네스로 상수를 정하지 않는다.** 후보를 좁히는 데만 쓰고, 값을 바꾸려면
배포 기기에서 재거나 CPU 상태를 고정할 것. 그리고 배치를 바꾸면 벡터도 달라지므로
(아래 MIN_WORTHWHILE_GAIN 주석) 재색인과 품질 재측정이 따라온다.

규율은 `test_embed_speed.py` 와 같다:
- **고정 청크 표본**만 잰다 (전체 인덱싱을 반복할 이유가 없다)
- **A→B→C→A→B→C 로 번갈아** 잰다. 배경 부하가 모든 후보에 균등하게 섞인다
- 라운드마다의 **중앙값**을 쓴다 (평균은 이상치 하나에 끌려간다)
- **첫 배치는 버린다** — ONNX 그래프 최적화가 그 배치에만 섞인다
- 측정 앞뒤로 **카나리**를 돌려 기기 상태가 변했는지 본다
- CPU 점유(process_time / perf_counter)를 함께 남긴다
"""

import json
import os
import statistics
import time
from pathlib import Path

import pytest

from app.core import embeddings
from app.core.chunker import chunk_files

pytestmark = pytest.mark.evaluation

# 후보 배치 크기. **최적점을 가운데 두고 양쪽을 열어 둔다** — 끝값이 이기면 그 바깥에
# 더 나은 값이 있는지 알 수 없다. 실측에서 128→1 이 단조 감소라 아래로 옮겨 왔고,
# 1 은 **더 내려갈 수 없는 바닥**이라(배치를 안 쓰는 것) 거기서 멈춘다.
# 현재 값은 `_candidates()` 가 자동으로 끼워 넣는다 — 구간을 어디로 옮기든 지금 값과의
# 차이를 그 회차 안에서 바로 읽을 수 있어야 한다.
#
# **후보를 적게 둘수록 한 라운드가 짧아 기기 상태가 덜 변한다.** 8개를 한 번에 재려다
# 라운드1 과 라운드3 사이에 부하가 바뀌어 후보 셋을 폐기한 적이 있다.
BATCH_SIZES = [1, 8, 64]


def _candidates() -> list[int]:
    return sorted({*BATCH_SIZES, embeddings.EMBED_BATCH_SIZE})

SAMPLE_CHUNKS = 200  # 표본 크기. 늘려도 배율은 안 변하고 시간만 는다
ROUNDS = 3

# 카나리를 **가장 작은 후보로** 잰다. 배치 32 로 재던 회차에서 기기가 느려졌는데
# 카나리는 4.7% 만 움직여 통과했다 — 그 느려짐이 호출 오버헤드 쪽이라 **작은 배치를
# 훨씬 세게 때렸기 때문**이다(배치 1 이 13% 느려질 때 배치 32 는 3.8%). 감지하려는
# 흔들림에 가장 민감한 조건으로 재야 카나리가 제 일을 한다.
CANARY_BATCH = 1

# 카나리 표본. **몇 초는 걸려야 한다** — 20개로 줄였더니 배치 1 에서 1.7초에 끝나
# 0.2초 노이즈가 14% 편차로 잡혀 본 측정(2.9~6.2%)이 멀쩡한 회차를 오탐했다.
# (test_embed_speed.py 가 같은 함정을 겪고 남긴 교훈인데 그대로 밟았다)
CANARY_CHUNKS = 60

# 폐기 기준 — **측정 전에 고정한다.** 나중에 정하면 마음에 드는 숫자에 맞추게 된다.
MAX_ROUND_SPREAD = 0.15  # 라운드 간 편차가 이보다 크면 그 후보 수치를 못 믿는다
MAX_CANARY_DRIFT = 0.10  # 앞뒤 카나리가 이보다 다르면 절대 시간을 못 믿는다

# 현재 값보다 이만큼은 빨라져야 바꿀 값어치가 있다. 라운드 편차가 3~4% 나오는 측정이라
# 그보다 작은 차이는 노이즈와 구분되지 않는다.
#
# **배치를 바꾸면 벡터도 달라진다.** 패딩은 어텐션 마스크로 가려지니 같을 줄 알았는데,
# 같은 저장소를 배치 32 와 1 로 각각 색인해 4,365청크를 짝지어 보니 코사인 평균 0.993,
# 최소 0.977 이었다(int8 ↔ fp32 차이와 같은 크기다). 배치 모양에 따라 다른 커널이
# 쓰이고 int8 양자화가 그 차이를 키우는 것으로 보인다.
# → **배치를 바꾸면 재색인이 따라오고, 검색 품질을 다시 재야 한다.**
MIN_WORTHWHILE_GAIN = 0.05

SOURCE_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "eval_sources"


def _sample_texts() -> list[str]:
    """고정 표본. 캐시된 평가 소스에서 SAMPLE_CHUNKS 개를 뽑는다.

    청킹은 결정적이고 소스도 캐시라, 몇 번을 돌려도 **같은 텍스트**가 나온다.

    **일정 간격으로 훑어 뽑는다(앞에서부터가 아니라).** 최적 배치는 청크 길이에
    좌우되는데(짧은 청크는 패딩 낭비가 적어 큰 배치의 이점이 사라진다), 앞 200개만
    뽑으면 저장소의 길이 분포가 아니라 **첫 몇 파일의 분포**를 재게 된다.
    실측에서 한 저장소는 앞 200개 평균이 401자인데 전체 중앙값은 744자였다.

    `EVAL_SOURCE` 를 주면 이름에 그 문자열이 든 캐시를 쓴다(없으면 사전순 첫 번째).
    저장소마다 길이 분포가 다르므로, 하나에서 나온 값을 규칙으로 삼기 전에
    다른 분포에서도 같은 답이 나오는지 봐야 한다.
    """
    caches = sorted(SOURCE_CACHE_DIR.glob("*.json"))
    if not caches:
        pytest.skip(
            "평가용 소스 캐시가 없습니다. 먼저 `pytest -m evaluation"
            " tests/test_search_quality.py` 를 한 번 돌려 캐시를 만드세요."
        )
    wanted = os.environ.get("EVAL_SOURCE", "")
    chosen = next((c for c in caches if wanted in c.stem), caches[0]) if wanted else caches[0]

    files = json.loads(chosen.read_text(encoding="utf-8"))
    # 토큰 재분할은 끈다 — 모든 배치 후보에 **같은 문자열**이 들어가야 한다.
    pieces = chunk_files(files)
    if len(pieces) < SAMPLE_CHUNKS:
        pytest.skip(f"표본이 부족합니다: {len(pieces)}개 (필요 {SAMPLE_CHUNKS}개)")
    step = len(pieces) // SAMPLE_CHUNKS
    print(f"\n표본 출처 {chosen.stem} (전체 {len(pieces)}청크에서 {step}개마다 하나)")
    return [pieces[i * step]["content"] for i in range(SAMPLE_CHUNKS)]


def _embed(model, texts: list[str], batch_size: int) -> tuple[float, float]:
    """(경과 초, CPU 점유율). 실제 경로와 같게 문서 접두어를 붙여 넣는다."""
    prefixed = [embeddings.document_text(t) for t in texts]
    wall0, cpu0 = time.perf_counter(), time.process_time()
    count = sum(1 for _ in model.embed(prefixed, batch_size=batch_size))
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    assert count == len(texts)
    return wall, cpu / wall if wall else 0.0


def _spread(values: list[float]) -> float:
    """중앙값 대비 최대 편차 비율. 라운드끼리 얼마나 흔들렸는지."""
    mid = statistics.median(values)
    return max(abs(v - mid) for v in values) / mid if mid else 0.0


def test_compare_batch_sizes(capsys):
    """배치 크기별 청크당 임베딩 시간을 인터리브로 비교한다. 단정하지 않고 측정만 한다."""
    texts = _sample_texts()
    canary = texts[:CANARY_CHUNKS]
    candidates = _candidates()

    with capsys.disabled():
        print(f"\n모델 {embeddings.EMBEDDING_MODEL}")
        print(f"표본 {len(texts)}청크 (평균 {statistics.mean(len(t) for t in texts):.0f}자)"
              f" · 후보 {candidates} · {ROUNDS}라운드 인터리브")

        t0 = time.perf_counter()
        model = embeddings._get_model()
        # 워밍업 1배치는 버린다 (그래프 최적화가 여기에만 섞인다).
        _embed(model, texts[: max(candidates)], embeddings.EMBED_BATCH_SIZE)
        print(f"  로드+워밍업 {time.perf_counter() - t0:.1f}s")

        canary_before = _embed(model, canary, CANARY_BATCH)[0]

        timings: dict[int, list[float]] = {b: [] for b in candidates}
        cpu_shares: dict[int, list[float]] = {b: [] for b in candidates}
        for rnd in range(1, ROUNDS + 1):
            for batch in candidates:  # A→B→C→A→B→C 순서가 이 루프의 전부다
                wall, cpu_share = _embed(model, texts, batch)
                timings[batch].append(wall)
                cpu_shares[batch].append(cpu_share)
                print(f"  라운드{rnd} 배치 {batch:4} {wall:7.1f}s"
                      f"  ({wall / len(texts) * 1000:6.1f}ms/청크, CPU {cpu_share:.1f}x)")

        canary_after = _embed(model, canary, CANARY_BATCH)[0]
        drift = abs(canary_after - canary_before) / canary_before

        _report(timings, cpu_shares, len(texts), canary_before, canary_after, drift)

    assert all(timings.values()), "측정된 시간이 없다 — 하네스를 의심하라"


def _report(timings, cpu_shares, sample, canary_before, canary_after, drift) -> None:
    print(f"\n{'=' * 74}")
    print(f"{'배치':>6} {'중앙값':>9} {'ms/청크':>9} {'편차':>7} {'CPU':>6}  판정")
    print("-" * 74)

    medians = {}
    for batch, values in timings.items():
        mid = statistics.median(values)
        medians[batch] = mid
        spread = _spread(values)
        cpu = statistics.median(cpu_shares[batch])
        verdict = "OK" if spread <= MAX_ROUND_SPREAD else f"폐기(편차>{MAX_ROUND_SPREAD:.0%})"
        current = " ← 현재" if batch == embeddings.EMBED_BATCH_SIZE else ""
        print(f"{batch:6} {mid:8.1f}s {mid / sample * 1000:8.1f} "
              f"{spread:6.1%} {cpu:5.1f}x  {verdict}{current}")

    print("-" * 74)
    # **CPU 점유가 이 측정의 전제다.** 최적 배치는 프로세스가 실제로 쓰는 코어 수에 따라
    # 뒤집힌다 — 실측에서 7.8코어일 때는 배치 1 이 32 보다 2.2배 빨랐는데, 같은 기기가
    # 3.4코어로 떨어지자 배치 32 가 1.2배 빠른 쪽으로 **순서가 뒤집혔다**. 코어가 적으면
    # 호출당 고정 비용이 상대적으로 커져 배치가 그것을 분산시키는 쪽이 이긴다.
    # 회차끼리 배율을 견주려면 이 값이 비슷해야 한다.
    cores = os.cpu_count() or 0
    share = statistics.median(
        statistics.median(v) for v in cpu_shares.values()
    )
    if cores and share < cores * 0.8:
        print(
            f"⚠ CPU 점유 {share:.1f}x / 코어 {cores}개 — 코어를 다 쓰지 못했다."
            " 다른 부하가 있거나 지속 부하로 코어가 파킹된 상태다."
            " **다른 회차와 배율을 견주지 말 것** (최적 배치가 코어 수에 따라 뒤집힌다)."
        )

    # 카나리가 넘었다고 회차를 버리지 않는다 — 무엇을 못 믿는지가 다르다.
    # 절대 시간은 못 믿지만 **배율은 인터리브가 지킨다** (느려짐이 모든 후보에 균등하게 실린다).
    verdict = (
        "OK" if drift <= MAX_CANARY_DRIFT
        else f"절대 시간 못 믿음(>{MAX_CANARY_DRIFT:.0%}) — 배율만 읽을 것"
    )
    print(f"카나리 {canary_before:.1f}s → {canary_after:.1f}s (편차 {drift:.1%})  {verdict}")

    best = min(medians, key=medians.get)
    current = embeddings.EMBED_BATCH_SIZE
    if current in medians and medians[current]:
        gain = (medians[current] - medians[best]) / medians[current]
        print(f"\n가장 빠른 배치: {best} ({medians[best] / sample * 1000:.1f}ms/청크)")
        if best == current:
            print(f"현재 값({current})이 이미 최적이다. 바꿀 것 없음.")
        elif gain < MIN_WORTHWHILE_GAIN:
            print(f"현재 값({current})보다 {gain:.1%} 빠르지만 기준({MIN_WORTHWHILE_GAIN:.0%})에"
                  f" 못 미친다 — 측정 노이즈와 구분되지 않는다. 바꾸지 말 것.")
        else:
            print(f"현재 값({current})보다 **{gain:.1%} 빠르다** — 바꿀 값어치가 있다.")
    print(f"{'=' * 74}\n")
