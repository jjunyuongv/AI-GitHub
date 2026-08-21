"""repos / repo_snapshots 통합 테스트. 실제 PostgreSQL 이 필요하다 (없으면 skip)."""

import pytest

from app.db import repos as repo_db
from app.db.pool import cursor

pytestmark = pytest.mark.usefixtures("db")

REPO = {
    "owner": "react",
    "name": "react",
    "display_owner": "React",
    "display_name": "React",
}
SNAPSHOT = {
    **REPO,
    "key_source": "pushed_at",
    "version": "20260814091233",
    "context": "## 레포지토리 정보\n- 이름: React/React",
    "summary": "요약 본문",
    "model": "claude-sonnet-5",
}


def _count(table: str) -> int:
    with cursor(commit=False) as cur:
        cur.execute(f"SELECT count(*) AS n FROM {table}")
        return cur.fetchone()["n"]


# --- 저장소 -----------------------------------------------------------------


def test_same_repo_is_inserted_once():
    repo_db.put_snapshot(**SNAPSHOT)
    repo_db.put_snapshot(**{**SNAPSHOT, "version": "20260815000000"})

    assert _count("repos") == 1
    assert _count("repo_snapshots") == 2


def test_display_name_follows_the_repo_rename():
    """저장소가 이전·개명되면 정식 표기를 최신으로 덮어쓴다."""
    repo_db.put_snapshot(**SNAPSHOT)
    repo_db.put_snapshot(
        **{**SNAPSHOT, "display_owner": "facebook", "version": "20260815000000"}
    )

    with cursor(commit=False) as cur:
        cur.execute("SELECT display_owner FROM repos")
        assert cur.fetchone()["display_owner"] == "facebook"


# --- 스냅샷 -----------------------------------------------------------------


def test_miss_then_hit():
    key = {k: SNAPSHOT[k] for k in ("owner", "name", "key_source", "version")}
    assert repo_db.get_snapshot(**key) is None

    repo_db.put_snapshot(**SNAPSHOT)

    found = repo_db.get_snapshot(**key)
    assert found["summary"] == "요약 본문"
    assert found["context"] == SNAPSHOT["context"]
    assert found["model"] == "claude-sonnet-5"


def test_new_version_misses():
    repo_db.put_snapshot(**SNAPSHOT)

    assert (
        repo_db.get_snapshot(
            owner="react", name="react", key_source="pushed_at", version="20260815000000"
        )
        is None
    )


def test_other_key_source_does_not_collide():
    """나중에 커밋 SHA로 바꿔도 pushed_at 으로 만든 옛 행과 섞이지 않는다."""
    repo_db.put_snapshot(**SNAPSHOT)

    assert (
        repo_db.get_snapshot(
            owner="react", name="react", key_source="commit_sha", version="20260814091233"
        )
        is None
    )


def test_same_version_overwrites_in_place():
    """재인덱싱: 같은 버전이면 행을 늘리지 않고 내용만 갱신한다 (id 유지 = 대화 유지)."""
    first = repo_db.put_snapshot(**SNAPSHOT)
    second = repo_db.put_snapshot(**{**SNAPSHOT, "summary": "새 요약", "model": "claude-haiku-4-5"})

    assert first["id"] == second["id"]
    assert _count("repo_snapshots") == 1
    assert second["summary"] == "새 요약"
    assert second["model"] == "claude-haiku-4-5"


def test_other_repos_are_untouched():
    repo_db.put_snapshot(**SNAPSHOT)
    repo_db.put_snapshot(
        **{
            **SNAPSHOT,
            "owner": "psf",
            "name": "requests",
            "display_owner": "psf",
            "display_name": "requests",
            "summary": "requests 요약",
        }
    )

    key = {k: SNAPSHOT[k] for k in ("owner", "name", "key_source", "version")}
    assert repo_db.get_snapshot(**key)["summary"] == "요약 본문"
    assert _count("repos") == 2
