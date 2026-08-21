"""색인 큐. 워커를 돌리지 않고 큐에 들어가는 것까지만 본다."""

import pytest

from app.db import index_status
from app.db import repos as repo_db
from app.services import index_queue

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


@pytest.fixture
def snapshot_id() -> int:
    return repo_db.put_snapshot(**SNAPSHOT)["id"]


@pytest.fixture
def no_worker(monkeypatch):
    """워커를 띄우지 않는다 — 테스트가 실제 인덱싱(네트워크·모델)을 시작하면 안 된다."""
    monkeypatch.setattr(index_queue, "_ensure_worker", lambda: None)


def test_submit_creates_a_build_and_queues_it(snapshot_id, no_worker):
    before = index_queue.pending_count()

    build_id = index_queue.submit(snapshot_id, "react", "react", table=TABLE)

    assert build_id is not None
    assert index_queue.pending_count() == before + 1
    assert index_status.get(snapshot_id, table=TABLE)["status"] == "running"


def test_duplicate_submit_does_not_queue_twice(snapshot_id, no_worker):
    """같은 대상을 두 번 넣으면 tarball 도 임베딩도 두 배로 든다."""
    first = index_queue.submit(snapshot_id, "react", "react", table=TABLE)
    before = index_queue.pending_count()

    second = index_queue.submit(snapshot_id, "react", "react", table=TABLE)

    assert first is not None
    assert second is None
    assert index_queue.pending_count() == before


def test_rebuild_is_allowed_once_the_previous_build_finished(snapshot_id, no_worker):
    """활성 색인이 있어도 다시 만들 수 있어야 한다 — 그게 재색인이다."""
    first = index_queue.submit(snapshot_id, "react", "react", table=TABLE)
    index_status.complete(first, 3)

    second = index_queue.submit(snapshot_id, "react", "react", table=TABLE)

    assert second is not None and second != first
    # 새 빌드가 끝나기 전까지 검색은 옛 빌드를 계속 본다.
    assert index_status.active_build_id(snapshot_id, table=TABLE) == first
