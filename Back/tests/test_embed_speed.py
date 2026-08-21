"""임베딩 처리량 비교 — 모델을 바꿀 때 얼마나 빨라지는지.

일반 테스트가 아니다. `-m evaluation` 을 붙였을 때만 돈다:

    pytest -m evaluation tests/test_embed_speed.py -s

**왜 이 하네스가 따로 있는가.** 전에는 전체 인덱싱 시간(74~96분)을 모델마다 한 번씩
재서 비교했는데, 한 저장소는 15% 느려지고 다른 저장소는 2.45배 빨라지는 정반대 결과가
나와 양쪽 다 철회했다. 원인은 **A 를 전부 잰 뒤 B 를 전부 잰 것**이다 — 그 사이의
배경 부하 변화가 통째로 한쪽 모델의 수치로 들어갔다.

그래서 이 하네스는:
- 전체 인덱싱을 재지 않는다. **고정 청크 표본**만 잰다 (96분짜리를 반복할 이유가 없다)
- **A→B→A→B→A→B 로 번갈아** 잰다. 부하가 양쪽에 균등하게 섞인다
- 라운드마다의 **중앙값**을 쓴다 (평균은 이상치 하나에 끌려간다)
- 각 모델의 **첫 배치는 버린다** — ONNX 그래프 최적화가 그 배치에만 섞인다
- 측정 앞뒤로 **카나리**를 돌려 기기 상태가 변했는지 본다
- CPU 점유(process_time / perf_counter)를 함께 남긴다. 이 값이 흔들린 회차는 못 믿는다

**그래도 시간은 2차 지표다.** 채택 여부는 검색 품질로 가른다 (test_search_quality.py).
여기서 나온 배율은 "대략 몇 배"로만 읽을 것.
"""

import json
import statistics
import time
from pathlib import Path

import pytest

from app.core import embeddings
from app.core.chunker import chunk_files

pytestmark = pytest.mark.evaluation

# 비교할 모델. 전부 E5 계열이라 접두어 규약이 같아 입력이 동일하다.
# (이름, fastembed 에 쓸 모델명, 차원, 가중치 저장소, 파일)
# 저장소·파일이 None 이면 fastembed 내장 등록을 쓴다.
MODELS = [
    ("e5-large (현재)", "intfloat/multilingual-e5-large", 1024, None, None),
    (
        "e5-large-int8",
        "intfloat/multilingual-e5-large-int8",
        1024,
        "intfloat/multilingual-e5-large",
        "onnx/model_qint8_avx512_vnni.onnx",
    ),
]

SAMPLE_CHUNKS = 200  # 표본 크기. 늘려도 배율은 안 변하고 시간만 는다
# 측정 앞뒤로 돌려 기기 상태를 보는 짧은 벤치. **가장 느린 모델로 잰다**(아래 참고) —
# 몇 초는 걸려야 0.1초 노이즈가 편차 기준을 넘기지 않는다.
CANARY_CHUNKS = 20
ROUNDS = 3

# 폐기 기준 — **측정 전에 고정한다.** 나중에 정하면 마음에 드는 숫자에 맞추게 된다.
MAX_ROUND_SPREAD = 0.15  # 라운드 간 편차가 이보다 크면 그 모델 수치를 못 믿는다
MAX_CANARY_DRIFT = 0.10  # 앞뒤 카나리가 이보다 다르면 회차 전체가 오염된 것이다

SOURCE_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "eval_sources"


def _sample_texts() -> list[str]:
    """고정 표본. 캐시된 평가 소스에서 앞에서부터 SAMPLE_CHUNKS 개를 뽑는다.

    청킹은 결정적이고 소스도 캐시라, 몇 번을 돌려도 **같은 텍스트**가 나온다.
    입력이 흔들리면 시간 차이가 모델 때문인지 입력 때문인지 가릴 수 없다.
    """
    caches = sorted(SOURCE_CACHE_DIR.glob("*.json"))
    if not caches:
        pytest.skip(
            "평가용 소스 캐시가 없습니다. 먼저 `pytest -m evaluation"
            " tests/test_search_quality.py` 를 한 번 돌려 캐시를 만드세요."
        )
    files = json.loads(caches[0].read_text(encoding="utf-8"))
    # 토큰 재분할은 모델의 토크나이저를 타므로 여기서는 끈다 — 두 모델에 **같은 문자열**이
    # 들어가야 한다. 재분할을 켜면 모델마다 다른 청크를 재게 되어 비교가 깨진다.
    pieces = chunk_files(files)
    texts = [p["content"] for p in pieces[:SAMPLE_CHUNKS]]
    if len(texts) < SAMPLE_CHUNKS:
        pytest.skip(f"표본이 부족합니다: {len(texts)}개 (필요 {SAMPLE_CHUNKS}개)")
    return texts


def _load(model_name: str, dim: int, source_repo=None, model_file=None):
    """모델 하나를 올린다. 우리 모듈의 등록 경로를 그대로 탄다.

    등록 인자는 모듈 전역에서 읽으므로 여기서 갈아끼운다 — 서비스는 설정 하나로
    한 모델만 쓰지만, 이 하네스는 한 프로세스에서 여러 모델을 번갈아 올려야 한다.
    """
    from fastembed import TextEmbedding

    embeddings.EMBEDDING_DIM = dim  # add_custom_model 에 넘어가는 값
    if source_repo:
        embeddings.EMBEDDING_SOURCE_REPO = source_repo
        embeddings.EMBEDDING_MODEL_FILE = model_file
    embeddings._register_if_custom(model_name)
    return TextEmbedding(
        model_name=model_name, cache_dir=embeddings.EMBEDDING_CACHE_DIR
    )


def _embed(model, texts: list[str]) -> tuple[float, float]:
    """(경과 초, CPU 점유율). 실제 경로와 같게 문서 접두어를 붙여 넣는다."""
    prefixed = [embeddings.document_text(t) for t in texts]
    wall0, cpu0 = time.perf_counter(), time.process_time()
    count = sum(1 for _ in model.embed(prefixed, batch_size=embeddings.EMBED_BATCH_SIZE))
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    assert count == len(texts)
    return wall, cpu / wall if wall else 0.0


def _spread(values: list[float]) -> float:
    """중앙값 대비 최대 편차 비율. 라운드끼리 얼마나 흔들렸는지."""
    mid = statistics.median(values)
    return max(abs(v - mid) for v in values) / mid if mid else 0.0


def test_compare_embedding_speed(capsys):
    """두 모델의 청크당 임베딩 시간을 인터리브로 비교한다. 단정하지 않고 측정만 한다."""
    texts = _sample_texts()
    canary = texts[:CANARY_CHUNKS]

    with capsys.disabled():
        print(f"\n표본 {len(texts)}청크 (평균 {statistics.mean(len(t) for t in texts):.0f}자)"
              f" · 배치 {embeddings.EMBED_BATCH_SIZE} · {ROUNDS}라운드 인터리브")

        loaded = []
        for label, name, dim, source_repo, model_file in MODELS:
            t0 = time.perf_counter()
            model = _load(name, dim, source_repo, model_file)
            # 워밍업 1배치는 버린다 (그래프 최적화가 여기에만 섞인다).
            _embed(model, texts[: embeddings.EMBED_BATCH_SIZE])
            print(f"  {label} 로드+워밍업 {time.perf_counter() - t0:.1f}s")
            loaded.append((label, model))

        # 카나리는 **가장 느린 모델로** 잰다. 작은 모델로 재면 20청크가 1초도 안 걸려
        # 0.1초 노이즈가 12% 편차로 잡힌다 — 본 측정이 3% 로 안정적인데도 회차가
        # 폐기되는 오탐이 실제로 났다. 기준은 그대로 두고 분해능을 10배로 올린다.
        canary_before = _embed(loaded[0][1], canary)[0]

        timings: dict[str, list[float]] = {label: [] for label, _ in loaded}
        cpu_shares: dict[str, list[float]] = {label: [] for label, _ in loaded}
        for rnd in range(1, ROUNDS + 1):
            for label, model in loaded:  # A→B→A→B… 순서가 이 루프의 전부다
                wall, cpu_share = _embed(model, texts)
                timings[label].append(wall)
                cpu_shares[label].append(cpu_share)
                print(f"  라운드{rnd} {label:16} {wall:7.1f}s"
                      f"  ({wall / len(texts) * 1000:6.1f}ms/청크, CPU {cpu_share:.1f}x)")

        canary_after = _embed(loaded[0][1], canary)[0]
        drift = abs(canary_after - canary_before) / canary_before

        _report(timings, cpu_shares, len(texts), canary_before, canary_after, drift)

    assert all(timings.values()), "측정된 시간이 없다 — 하네스를 의심하라"


def _report(timings, cpu_shares, sample, canary_before, canary_after, drift) -> None:
    print(f"\n{'=' * 74}")
    print(f"{'모델':18} {'중앙값':>9} {'ms/청크':>9} {'편차':>7} {'CPU':>6}  판정")
    print("-" * 74)

    medians = {}
    for label, values in timings.items():
        mid = statistics.median(values)
        medians[label] = mid
        spread = _spread(values)
        cpu = statistics.median(cpu_shares[label])
        verdict = "OK" if spread <= MAX_ROUND_SPREAD else f"폐기(편차>{MAX_ROUND_SPREAD:.0%})"
        print(f"{label:18} {mid:8.1f}s {mid / sample * 1000:8.1f} "
              f"{spread:6.1%} {cpu:5.1f}x  {verdict}")

    print("-" * 74)
    # 카나리가 넘었다고 회차를 버리지 않는다 — 무엇을 못 믿는지가 다르다.
    # 절대 시간(82초)은 측정 중 기기가 변했으므로 못 믿지만, **배율은 인터리브가 지킨다.**
    # A→B→A→B 로 재면 느려짐이 양쪽에 균등하게 실려 비율에서 상쇄된다
    # (실측: 카나리가 11~12% 흔들린 두 회차에서 라운드 편차는 2~4%, 배율은 9.42/9.27배).
    verdict = (
        "OK" if drift <= MAX_CANARY_DRIFT
        else f"절대 시간 못 믿음(>{MAX_CANARY_DRIFT:.0%}) — 배율만 읽을 것"
    )
    print(f"카나리 {canary_before:.1f}s → {canary_after:.1f}s (편차 {drift:.1%})  {verdict}")
    if drift > MAX_CANARY_DRIFT:
        print("  측정 앞뒤로 기기가 느려졌다(둘 다 뒤가 느리면 발열로 클럭이 내려간 것이다).")

    labels = list(medians)
    if len(labels) == 2 and medians[labels[1]]:
        ratio = medians[labels[0]] / medians[labels[1]]
        print(f"\n{labels[1]} 가 {labels[0]} 보다 **{ratio:.2f}배 빠르다**")
    print("배치 크기는 두 모델에 같은 값을 썼다 — 32 는 e5-large 기준으로 고른 값이라,")
    print("작은 모델을 채택하면 배치를 다시 튜닝해야 이 배율보다 더 빨라질 수 있다.")
    print(f"{'=' * 74}\n")
