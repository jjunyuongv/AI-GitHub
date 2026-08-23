"""chat_sessions / messages 통합 테스트. 실제 PostgreSQL 이 필요하다 (없으면 skip)."""

import pytest

from app.db import chats
from app.db import repos as repo_db
from app.db.pool import cursor

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def snapshot() -> dict:
    return repo_db.put_snapshot(
        owner="react",
        name="react",
        display_owner="React",
        display_name="React",
        key_source="pushed_at",
        version="20260814091233",
        context="## 레포지토리 정보\n- 이름: React/React",
        summary="요약 본문",
        model="claude-sonnet-5",
    )


def _count(table: str) -> int:
    with cursor(commit=False) as cur:
        cur.execute(f"SELECT count(*) AS n FROM {table}")
        return cur.fetchone()["n"]


# --- 세션 -------------------------------------------------------------------


def test_session_carries_context_and_display_name(snapshot):
    """후속 질문에 필요한 것(컨텍스트·요약)과 화면에 쓸 정식 표기를 한 번에 가져온다."""
    session_id = chats.create_session(snapshot["id"])

    session = chats.get_session(session_id)

    assert session["context"] == snapshot["context"]
    assert session["summary"] == "요약 본문"
    assert session["display_owner"] == "React"
    assert session["display_name"] == "React"
    assert session["last_message_at"] is None


def test_unknown_session_is_none():
    assert chats.get_session("00000000-0000-0000-0000-000000000000") is None


def test_two_analyses_make_two_sessions(snapshot):
    """같은 스냅샷을 여러 대화가 공유한다 (재분석할 때마다 새 대화)."""
    first = chats.create_session(snapshot["id"])
    second = chats.create_session(snapshot["id"])

    assert first != second
    assert _count("chat_sessions") == 2


# --- 메시지 -----------------------------------------------------------------


def test_exchange_saves_both_sides_in_order(snapshot):
    session_id = chats.create_session(snapshot["id"])

    chats.add_exchange(session_id, "인증은 어디서 처리해?", "auth 디렉터리에서 처리합니다.")

    messages = chats.list_messages(session_id)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "인증은 어디서 처리해?"
    assert messages[1]["content"] == "auth 디렉터리에서 처리합니다."


def test_exchange_stamps_last_message_at(snapshot):
    session_id = chats.create_session(snapshot["id"])

    chats.add_exchange(session_id, "질문", "답변")

    assert chats.get_session(session_id)["last_message_at"] is not None


def test_limit_keeps_the_recent_messages_in_order(snapshot):
    session_id = chats.create_session(snapshot["id"])
    for i in range(5):
        chats.add_exchange(session_id, f"질문{i}", f"답변{i}")

    recent = chats.list_messages(session_id, limit=4)

    # 최근 4개(질문3·답변3·질문4·답변4)를 오래된 순으로.
    assert [m["content"] for m in recent] == ["질문3", "답변3", "질문4", "답변4"]


def test_empty_answer_takes_its_question_with_it(snapshot):
    """빈 답변은 **짝인 질문과 함께** 빠진다.

    빈 문자열이 그대로 저장된 적이 있고 그 행들이 요청마다 이력에 실려 갔다.
    답변만 빼면 user 가 연속으로 남아, 답을 못 받은 질문만 화면에 떠 있게 된다.
    """
    session_id = chats.create_session(snapshot["id"])
    chats.add_exchange(session_id, "질문0", "답변0")
    chats.add_exchange(session_id, "질문1", "")
    chats.add_exchange(session_id, "질문2", "답변2")

    kept = chats.list_messages(session_id)

    # 빈 쌍만 사라지고 **정상 쌍은 하나도 안 빠진다** (뒤쪽이 진짜 방어선이다).
    assert [m["content"] for m in kept] == ["질문0", "답변0", "질문2", "답변2"]


def test_whitespace_only_answer_counts_as_empty(snapshot):
    """공백만 든 답변도 화면에서는 똑같이 빈 말풍선이다."""
    session_id = chats.create_session(snapshot["id"])
    chats.add_exchange(session_id, "질문", "  \n ")

    assert chats.list_messages(session_id) == []


def test_a_question_without_an_answer_survives(snapshot):
    """마지막 행에서 lead() 가 NULL 이 된다. 조건이 NULL 이면 WHERE 가 조용히 버린다."""
    session_id = chats.create_session(snapshot["id"])
    chats.add_exchange(session_id, "질문0", "답변0")
    with cursor() as cur:
        cur.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
            (session_id, "user", "짝 없는 질문"),
        )

    kept = chats.list_messages(session_id)

    assert [m["content"] for m in kept] == ["질문0", "답변0", "짝 없는 질문"]


def test_limit_counts_only_the_kept_messages(snapshot):
    """limit 은 **거른 뒤** 개수로 세야 한다.

    자른 뒤에 거르면 빈 행이 limit 을 잡아먹어, LLM 에 가는 이력이
    MAX_HISTORY_MESSAGES 보다 짧아진다.
    """
    session_id = chats.create_session(snapshot["id"])
    chats.add_exchange(session_id, "질문0", "답변0")
    chats.add_exchange(session_id, "질문1", "답변1")
    chats.add_exchange(session_id, "질문2", "")  # 최근 4행 안에 든다
    chats.add_exchange(session_id, "질문3", "답변3")

    # 남는 것은 6개. limit 이 그보다 **작을 때** — 자른 뒤에 거르면 2개만 나온다.
    assert [m["content"] for m in chats.list_messages(session_id, limit=4)] == [
        "질문1", "답변1", "질문3", "답변3",
    ]
    # limit 이 남는 개수보다 **클 때** — 채우지도 넘치지도 않는다.
    assert len(chats.list_messages(session_id, limit=10)) == 6


def test_messages_go_away_with_the_session(snapshot):
    session_id = chats.create_session(snapshot["id"])
    chats.add_exchange(session_id, "질문", "답변")

    with cursor() as cur:
        cur.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))

    assert _count("messages") == 0


def test_role_is_constrained(snapshot):
    """스키마의 CHECK 제약이 살아 있는지 — 잘못된 role 은 저장되지 않는다."""
    import psycopg

    session_id = chats.create_session(snapshot["id"])

    with pytest.raises(psycopg.Error):
        with cursor() as cur:
            cur.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                (session_id, "system", "본문"),
            )
