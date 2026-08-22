"""백그라운드 인덱싱 통합 테스트.

실제 PostgreSQL 은 쓰지만 GitHub 과 임베딩 모델은 대역으로 갈아끼운다 —
테스트가 네트워크와 2GB 모델에 묶이면 안 된다.
"""

import logging

import psycopg
import pytest

from app.db import index_status
from app.db import chunks as chunk_store
from app.db import repos as repo_db
from app.db import sources as source_store
from app.services import indexer

pytestmark = pytest.mark.usefixtures("db")

TABLE = "code_chunks_1024"

SNAPSHOT = {
    "owner": "react",
    "name": "react",
    "display_owner": "React",
    "display_name": "React",
    "key_source": "pushed_at",
    "version": "20260814091233",
    "context": "## 레포지토리 정보",
    "summary": "요약 본문",
    "model": "claude-sonnet-5",
}

FILES = {"app/main.py": "def run():\n    return 1\n"}


@pytest.fixture
def snapshot_id() -> int:
    return repo_db.put_snapshot(**SNAPSHOT)["id"]


def _index_now(snapshot_id: int, table: str = TABLE, files=None) -> int:
    """큐 워커가 하는 일을 그 자리에서 한다 (빌드 시작 → 인덱싱). build_id 를 준다."""
    build_id = index_status.begin(snapshot_id, table=table)
    assert build_id is not None
    indexer.run_build(build_id, snapshot_id, "react", "react", "", table, files)
    return build_id


@pytest.fixture
def fake_sources(monkeypatch):
    """수집·청킹·임베딩을 대역으로. 청크 3개짜리 저장소를 흉내 낸다."""
    pieces = [
        {"path": "app/main.py", "language": "python", "start_line": i,
         "end_line": i + 2, "content": f"def f{i}(): pass"}
        for i in range(3)
    ]
    monkeypatch.setattr(indexer, "fetch_source_files", lambda o, r, ref="": FILES)
    # chunk_files 는 토큰 재분할용 카운터를 주입으로 받는다 (**kw 로 흘려보낸다).
    monkeypatch.setattr(indexer, "chunk_files", lambda files, **kw: pieces)
    # 토크나이저 대역 — 실제 함수는 2GB 모델을 올린다.
    monkeypatch.setattr(indexer, "input_limit", lambda: 512)
    monkeypatch.setattr(indexer, "count_tokens", lambda texts: [10] * len(texts))

    def fake_embed(texts, on_progress=None):
        for i in range(1, len(texts) + 1):
            if on_progress:
                on_progress(i)
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(indexer, "embed_documents", fake_embed)
    # 이 대역 저장소는 아주 작아서 그냥 두면 전체 주입으로 새어 나간다.
    # 여기 테스트들은 검색 색인 경로가 대상이므로 우회를 명시적으로 끈다.
    monkeypatch.setattr(indexer, "FULL_INJECTION_MAX_TOKENS", 0)
    return pieces


@pytest.fixture
def full_injection(monkeypatch):
    """전체 주입을 켠다. 토큰 계산은 대역으로 — 실제 함수는 Claude API 를 부른다."""
    monkeypatch.setattr(indexer, "fetch_source_files", lambda o, r, ref="": FILES)
    monkeypatch.setattr(indexer, "FULL_INJECTION_MAX_TOKENS", 1000)
    monkeypatch.setattr(indexer, "FULL_INJECTION_MAX_SOURCE_BYTES", 500 * 1024)
    monkeypatch.setattr(indexer, "count_input_tokens", lambda text: 900)


def test_handed_off_sources_skip_the_download(snapshot_id, fake_sources, monkeypatch):
    """**넘겨받은 소스가 있으면 tarball 을 다시 받지 않는다.**

    /analyze 가 정적분석을 하려고 방금 받은 것이다. 버리면 새 스냅샷마다 두 번 받게
    되는데 아카이브 다운로드는 core 와 별개 제한을 받는다.
    """
    def must_not_fetch(owner, repo, ref=""):
        pytest.fail("넘겨받은 소스가 있는데 tarball 을 다시 받았다")

    monkeypatch.setattr(indexer, "fetch_source_files", must_not_fetch)

    build_id = _index_now(snapshot_id, files=FILES)

    assert index_status.get(snapshot_id, table=TABLE)["status"] == "completed"
    assert chunk_store.count(build_id, table=TABLE) == 3


def test_without_handoff_it_downloads(snapshot_id, fake_sources):
    """넘겨받은 것이 없으면(캐시 히트·정적분석 실패) 스스로 받는다."""
    build_id = _index_now(snapshot_id)
    assert chunk_store.count(build_id, table=TABLE) == 3


def test_oversized_sources_are_not_handed_off(monkeypatch):
    """**큐에 수십 MB 를 붙들지 않는다.** 상한을 넘으면 색인이 스스로 받게 둔다.

    수집 상한이 파일 3,000개 × 200KB 라 이론상 600MB 까지 가능하다.
    """
    from app.services import index_queue

    submitted = {}
    monkeypatch.setattr(indexer.index_status, "is_completed", lambda *a, **kw: False)
    # **모듈 객체의 함수를 갈아끼운다.** sys.modules 를 치환하는 방식은
    # `from app.services import index_queue` 가 패키지 속성을 먼저 보기 때문에 안 먹는다.
    monkeypatch.setattr(
        index_queue, "submit",
        lambda snapshot_id, owner, repo, ref="", table=None, files=None: (
            submitted.update(files=files) or 1
        ),
    )

    big = {"a.py": "x" * (indexer.MAX_HANDOFF_CHARS + 1)}
    indexer.start(1, "o", "r", files=big)
    assert submitted["files"] is None, "상한을 넘은 소스를 큐에 넘겼다"

    small = {"a.py": "x"}
    indexer.start(1, "o", "r", files=small)
    assert submitted["files"] == small


def test_small_repo_skips_indexing_and_stores_the_bundle(snapshot_id, full_injection):
    """임계값 이하면 임베딩을 만들지 않는다 — 그게 이 경로의 목적이다."""
    build_id = _index_now(snapshot_id)

    row = index_status.get(snapshot_id, table=TABLE)
    assert row["status"] == "completed"          # 배너 없이 바로 답할 수 있어야 한다
    assert chunk_store.count(build_id, table=TABLE) == 0

    snapshot = repo_db.get_snapshot(
        owner=SNAPSHOT["owner"], name=SNAPSHOT["name"],
        key_source=SNAPSHOT["key_source"], version=SNAPSHOT["version"],
    )
    assert snapshot["source_tokens"] == 900
    assert "app/main.py" in snapshot["source_bundle"]


# --- 소스 원문 보관 -----------------------------------------------------------


def test_full_injection_path_still_stores_the_source(snapshot_id, full_injection):
    """**이 테스트가 소스 보관 작업 전체의 이유다.**

    전에는 원문이 남는 곳이 전체 주입 번들뿐이었다. 그러면 소스가 이미 프롬프트에
    통째로 들어가 도구가 필요 없는 저장소에만 원문이 있고, 정작 큰 저장소에는 없다.
    보관은 전체 주입 판정보다 **앞**에서 일어나야 그 역설이 풀린다.
    """
    _index_now(snapshot_id)

    assert source_store.count(snapshot_id) == 1
    assert source_store.get_file(snapshot_id, "app/main.py") == FILES["app/main.py"]


def test_rag_path_stores_the_source_too(snapshot_id, fake_sources):
    """검색 색인을 만드는 경로에서도 원문을 보관한다. 청크와 함께 남는다."""
    build_id = _index_now(snapshot_id)

    assert chunk_store.count(build_id, table=TABLE) == 3
    assert source_store.get_file(snapshot_id, "app/main.py") == FILES["app/main.py"]


def test_oversized_source_stores_nothing_at_all(
    snapshot_id, fake_sources, monkeypatch, caplog
):
    """상한을 넘으면 **한 행도** 넣지 않는다. 잘라서 일부만 넣지 않는다.

    일부만 보관하면 도구의 "없습니다"가 "저장소에 없다"인지 "잘려서 없다"인지
    구분되지 않아, 없다는 답이 거짓이 된다. 색인 자체는 그대로 성공해야 한다.

    **파일을 셋 주고 상한을 둘만 들어갈 크기로 잡는다.** 파일이 하나면 자르기와
    전부 포기가 같은 결과를 내서 이 테스트가 아무것도 못 잡는다 — 실제로 처음엔
    그랬고, 자르는 변이가 통과했다.
    """
    monkeypatch.setattr(
        indexer, "fetch_source_files",
        lambda o, r, ref="": {"a.py": "x = 1\n", "b.py": "y = 2\n", "c.py": "z = 3\n"},
    )
    monkeypatch.setattr(indexer, "MAX_STORED_SOURCE_BYTES", 12)  # 18바이트 중 둘이 들어갈 크기

    with caplog.at_level(logging.WARNING, logger="app.services.indexer"):
        build_id = _index_now(snapshot_id)

    assert source_store.count(snapshot_id) == 0          # 부분 보관이 아니라 정확히 0
    assert index_status.get(snapshot_id, table=TABLE)["status"] == "completed"
    assert chunk_store.count(build_id, table=TABLE) == 3
    assert any("보관 상한" in r.message for r in caplog.records)


def test_zero_cap_disables_the_limit(snapshot_id, fake_sources, monkeypatch):
    """0 은 '제한 없음'이다 — 다른 상한들과 같은 규칙."""
    monkeypatch.setattr(indexer, "MAX_STORED_SOURCE_BYTES", 0)

    _index_now(snapshot_id)

    assert source_store.count(snapshot_id) == 1


def test_indexing_survives_a_source_store_failure(snapshot_id, fake_sources, monkeypatch):
    """보관이 실패해도 색인은 성공한다 — _prune·_report 와 같은 방침이다."""
    def boom(snapshot_id, files):
        raise psycopg.OperationalError("보관 실패")

    monkeypatch.setattr(indexer.source_store, "put_files", boom)

    build_id = _index_now(snapshot_id)

    assert index_status.get(snapshot_id, table=TABLE)["status"] == "completed"
    assert chunk_store.count(build_id, table=TABLE) == 3


def test_reindexing_replaces_the_stored_source(snapshot_id, fake_sources, monkeypatch):
    """파일이 줄어들면 옛 행이 남지 않는다. 남으면 도구가 없는 파일을 읽어 준다."""
    monkeypatch.setattr(
        indexer, "fetch_source_files",
        lambda o, r, ref="": {"a.py": "x = 1\n", "b.py": "y = 2\n"},
    )
    _index_now(snapshot_id)
    assert source_store.count(snapshot_id) == 2

    monkeypatch.setattr(indexer, "fetch_source_files", lambda o, r, ref="": {"a.py": "x = 1\n"})
    _index_now(snapshot_id)

    assert source_store.list_paths(snapshot_id) == ["a.py"]


def test_repo_over_the_token_threshold_falls_back_to_indexing(
    snapshot_id, fake_sources, full_injection, monkeypatch
):
    """임계값을 넘으면 평소대로 색인한다. 바이트가 작아도 토큰이 판정한다."""
    monkeypatch.setattr(indexer, "FULL_INJECTION_MAX_TOKENS", 1000)
    monkeypatch.setattr(indexer, "count_input_tokens", lambda text: 1001)

    build_id = _index_now(snapshot_id)

    assert chunk_store.count(build_id, table=TABLE) == 3


def test_byte_gate_rejects_before_counting_tokens(
    snapshot_id, fake_sources, full_injection, monkeypatch
):
    """사전 게이트에 걸리면 토큰을 세지 않는다 — 세는 것 자체가 API 왕복이다."""
    counted = []
    monkeypatch.setattr(indexer, "FULL_INJECTION_MAX_TOKENS", 1000)
    monkeypatch.setattr(indexer, "FULL_INJECTION_MAX_SOURCE_BYTES", 1)
    monkeypatch.setattr(
        indexer, "count_input_tokens", lambda text: counted.append(text) or 1
    )

    build_id = _index_now(snapshot_id)

    assert counted == []
    assert chunk_store.count(build_id, table=TABLE) == 3


def test_unmeasurable_bundle_falls_back_to_the_character_estimate(monkeypatch):
    """토큰을 못 세도 멈추지 않는다. 추정값은 실제보다 많게 잡아 우회를 덜 켠다."""
    monkeypatch.setattr(indexer, "count_input_tokens", lambda text: None)

    bundle, tokens = indexer.measure_bundle(FILES)

    assert tokens == round(len(bundle) / 2.0)


def test_indexing_stores_chunks_and_completes(snapshot_id, fake_sources):
    build_id = _index_now(snapshot_id)

    row = index_status.get(snapshot_id, table=TABLE)
    assert row["status"] == "completed"
    assert (row["chunks_done"], row["chunks_total"]) == (3, 3)
    assert chunk_store.count(build_id, table=TABLE) == 3


def test_completed_build_records_the_current_chunk_rule(snapshot_id, fake_sources):
    """규칙을 남겨야 나중에 이 색인이 낡았는지 판단할 수 있다."""
    from app.core.chunk_rule import rule_version

    build_id = index_status.begin(snapshot_id, table=TABLE, chunk_rule=rule_version())
    indexer.run_build(build_id, snapshot_id, "react", "react", "", TABLE)

    row = index_status.get(snapshot_id, table=TABLE)
    assert row["chunk_rule"] == rule_version()
    assert index_status.stale(rule_version(), table=TABLE) == []


def test_progress_is_reported_while_embedding(snapshot_id, fake_sources, monkeypatch):
    """진행률은 청크 수 기준이다. 임베딩 도중에 값이 올라가야 화면에 진행이 보인다."""
    seen = []
    real_advance = index_status.advance
    monkeypatch.setattr(
        index_status, "advance",
        lambda bid, done: (seen.append(done), real_advance(bid, done))[1],
    )

    _index_now(snapshot_id)

    assert seen == [1, 2, 3]


def test_failure_is_recorded_with_its_reason(snapshot_id, monkeypatch):
    """실패는 '진행 중'과 구분돼야 한다 — 화면이 사유를 보여줄 근거다."""

    def boom(owner, repo, ref=""):
        raise RuntimeError("저장소 아카이브가 너무 큽니다 (500MB 초과).")

    monkeypatch.setattr(indexer, "fetch_source_files", boom)

    _index_now(snapshot_id)

    row = index_status.get(snapshot_id, table=TABLE)
    assert row["status"] == "failed"
    assert "500MB" in row["error"]


def test_rebuild_keeps_serving_the_old_chunks_until_it_finishes(
    snapshot_id, fake_sources, monkeypatch
):
    """재색인 중에도 검색은 옛 빌드를 본다 — 제자리 교체를 없앤 이유다."""
    first = _index_now(snapshot_id)
    assert indexer.is_ready(snapshot_id, table=TABLE) is True

    # 새 빌드를 시작만 하고 끝내지 않는다.
    second = index_status.begin(snapshot_id, table=TABLE)
    assert second is not None

    assert indexer.is_ready(snapshot_id, table=TABLE) is True
    assert index_status.active_build_id(snapshot_id, table=TABLE) == first
    assert chunk_store.count(first, table=TABLE) == 3


def test_start_does_not_reindex_a_completed_snapshot(snapshot_id, fake_sources, monkeypatch):
    """첫 분석 뒤 다시 분석해도 tarball 을 또 받지 않는다.

    규칙이 낡았어도 여기서 자동으로 다시 만들지 않는다 — 배포 직후 전 저장소가
    한꺼번에 임베딩을 시작하면 그게 곧 장애다.
    """
    _index_now(snapshot_id)

    def fail_if_called(*a, **kw):
        raise AssertionError("이미 인덱싱된 스냅샷을 다시 수집했다")

    monkeypatch.setattr(indexer, "fetch_source_files", fail_if_called)

    assert indexer.start(snapshot_id, "react", "react", table=TABLE) is False


def test_start_does_not_reindex_an_empty_repository(snapshot_id, monkeypatch):
    """소스가 없는 저장소(청크 0개)도 한 번만 인덱싱한다.

    청크 존재 여부로 완료를 판단하던 시절에는 질문마다 tarball 을 다시 받았다.
    """
    monkeypatch.setattr(indexer, "fetch_source_files", lambda o, r, ref="": {})
    monkeypatch.setattr(indexer, "chunk_files", lambda files, **kw: [])
    monkeypatch.setattr(indexer, "embed_documents", lambda texts, on_progress=None: [])
    monkeypatch.setattr(indexer, "input_limit", lambda: 512)
    monkeypatch.setattr(indexer, "count_tokens", lambda texts: [])

    build_id = _index_now(snapshot_id)

    assert chunk_store.count(build_id, table=TABLE) == 0
    assert indexer.is_ready(snapshot_id, table=TABLE) is True
    assert indexer.start(snapshot_id, "react", "react", table=TABLE) is False


def test_search_is_blocked_until_the_first_index_finishes(snapshot_id, fake_sources):
    """진행 중인 인덱스로 검색하면 아직 임베딩하지 않은 코드가 '없는 코드'로 보인다."""
    build_id = index_status.begin(snapshot_id, table=TABLE)

    assert indexer.is_ready(snapshot_id, table=TABLE) is False

    indexer.run_build(build_id, snapshot_id, "react", "react", "", TABLE)

    assert indexer.is_ready(snapshot_id, table=TABLE) is True


def test_old_builds_are_pruned_after_a_rebuild(snapshot_id, fake_sources):
    """옛 빌드가 무한정 쌓이지 않아야 한다 (활성 + 직전 하나만 남긴다)."""
    for _ in range(3):
        _index_now(snapshot_id)

    builds = index_status.list_builds(snapshot_id, table=TABLE)
    assert len(builds) == 2
