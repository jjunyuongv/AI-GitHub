"""저장소 정리. 실제 PostgreSQL 이 필요하다 (없으면 skip)."""

import pytest

from app.db import index_status
from app.db import chats
from app.db import users
from app.db import repos as repo_db
from app.db.pool import cursor
from app.services import cleanup

pytestmark = pytest.mark.usefixtures("db")

# 이 파일이 "지금 쓰는 테이블"로 삼는 값.
TABLE = "code_chunks_1024"


@pytest.fixture(autouse=True)
def chunk_table_fixed(monkeypatch):
    """`CHUNK_TABLE` 을 TABLE 로 **명시적으로 고정한다.**

    안 하면 테스트가 개발자의 `.env` 에 좌우된다 — 모델을 바꿔 `CHUNK_TABLE` 이 달라지자
    "지금 쓰는 테이블은 비울 수 없다"를 확인하는 테스트가 깨졌다(그 테이블이 더는
    쓰이는 테이블이 아니게 됐으므로). 같은 이유로 `test_embeddings` 도 접두어를
    monkeypatch 로 비운다.
    """
    from app.db import chunks as chunk_store

    # 각 모듈이 값을 복사해 갔으므로 전부 갈아끼운다.
    monkeypatch.setattr(chunk_store, "CHUNK_TABLE", TABLE)
    monkeypatch.setattr(index_status, "CHUNK_TABLE", TABLE)
    monkeypatch.setattr(cleanup, "CHUNK_TABLE", TABLE)

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


def _older_snapshot(version: str) -> int:
    return repo_db.put_snapshot(**{**SNAPSHOT, "version": version})["id"]


def _age_session(session_id: str, hours: int) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE chat_sessions SET created_at = now() - make_interval(hours => %s) "
            "WHERE id = %s",
            (hours, session_id),
        )


def test_dry_run_deletes_nothing(snapshot_id):
    """지우는 것은 되돌릴 수 없다. 기본은 무엇이 지워질지 보여주기만 한다."""
    session = chats.create_session(snapshot_id)
    _age_session(session, cleanup.EMPTY_SESSION_GRACE_HOURS + 1)

    report = cleanup.run(apply=False)

    assert report["applied"] is False
    assert report["found"]["empty_sessions"] >= 1
    assert report["deleted"] == {}
    assert chats.get_session(session) is not None


def test_empty_sessions_are_removed_after_the_grace_period(snapshot_id):
    session = chats.create_session(snapshot_id)
    _age_session(session, cleanup.EMPTY_SESSION_GRACE_HOURS + 1)

    cleanup.run(apply=True)

    assert chats.get_session(session) is None


def test_a_fresh_empty_session_is_kept(snapshot_id):
    """/analyze 는 분석할 때마다 세션을 만들고, 사용자는 요약을 읽은 뒤에 첫 질문을 한다.

    유예 시간 없이 지우면 질문하는 순간 세션이 사라진다.
    """
    session = chats.create_session(snapshot_id)  # 방금 만든 세션

    cleanup.run(apply=True)

    assert chats.get_session(session) is not None


def test_a_session_with_messages_is_kept(snapshot_id):
    session = chats.create_session(snapshot_id)
    chats.add_exchange(session, "질문", "답변")
    _age_session(session, cleanup.EMPTY_SESSION_GRACE_HOURS * 10)

    cleanup.run(apply=True)

    assert chats.get_session(session) is not None


def test_snapshot_referenced_by_a_conversation_is_never_removed(snapshot_id):
    """스냅샷을 지우면 그 대화가 볼 코드와 컨텍스트가 사라진다."""
    newer = _older_snapshot("20260901000000")  # 이 저장소의 최신이 된다
    session = chats.create_session(snapshot_id)  # 옛 스냅샷을 참조하는 대화
    chats.add_exchange(session, "질문", "답변")

    cleanup.run(apply=True)

    assert repo_db.get_snapshot_repo(snapshot_id) is not None
    assert repo_db.get_snapshot_repo(newer) is not None


def test_orphan_snapshot_is_removed_but_the_newest_is_kept(snapshot_id):
    """최신은 남긴다 — 다음 분석이 그것을 요약 캐시로 쓴다."""
    newest = _older_snapshot("20260901000000")

    report = cleanup.run(apply=True)

    assert report["deleted"]["orphan_snapshots"] >= 1
    assert repo_db.get_snapshot_repo(snapshot_id) is None
    assert repo_db.get_snapshot_repo(newest) is not None


def test_unused_dimension_table_is_emptied(snapshot_id):
    """모델을 바꾸면 그 전 차원의 테이블은 아무도 읽지 않는다."""
    build_id = index_status.begin(snapshot_id, table="code_chunks")
    index_status.complete(build_id, 1)
    with cursor() as cur:
        cur.execute(
            """INSERT INTO code_chunks
                   (build_id, snapshot_id, path, language, start_line, end_line,
                    content, embedding)
               VALUES (%s, %s, 'a.py', 'python', 1, 5, 'print(1)', %s::vector)""",
            (build_id, snapshot_id, [0.0] * 768),
        )

    assert cleanup.survey()["unused_table_chunks"]["code_chunks"] == 1

    report = cleanup.run(apply=True)

    assert report["deleted"]["unused_table_chunks"]["code_chunks"] == 1
    assert report["after"]["unused_table_chunks"]["code_chunks"] == 0


def test_the_table_in_use_is_never_emptied(snapshot_id):
    """지금 쓰는 테이블을 비우면 모든 대화가 코드를 잃는다."""
    from app.db import chunks as chunk_store

    with pytest.raises(ValueError):
        chunk_store.delete_unused_table(TABLE)


def test_expired_logins_are_cleaned_but_live_ones_stay(snapshot_id):
    """정리가 **만료된 것만** 지우는지. 양쪽을 한 테스트에 둔다.

    살아 있는 쪽을 안 보면 조건을 넓히는 변이(`DELETE FROM logins`)가 통과하고,
    그러면 정리가 돌 때마다 모두가 로그아웃된다.

    `users.delete_expired()` 자체는 tests/test_db_users.py 가 따로 본다 —
    여기서 재는 것은 **정리 경로에 연결돼 있는가** 다.
    """
    user_id = users.upsert(4242, "octocat", None)
    alive = users.create_login(user_id, days=14)
    users.create_login(user_id, days=-1)

    assert cleanup.survey()["expired_logins"] == 1

    report = cleanup.run(apply=True)

    assert report["deleted"]["expired_logins"] == 1
    assert users.get_login(alive) is not None
