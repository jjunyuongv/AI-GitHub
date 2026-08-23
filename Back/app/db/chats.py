"""chat_sessions / messages 쿼리."""

from app.db.pool import cursor


def create_session(snapshot_id: int) -> str:
    """대화를 시작한다. 이 세션은 끝까지 이 스냅샷(=이 시점의 코드)만 본다."""
    with cursor() as cur:
        cur.execute(
            "INSERT INTO chat_sessions (snapshot_id) VALUES (%s) RETURNING id",
            (snapshot_id,),
        )
        return str(cur.fetchone()["id"])


def get_session(session_id: str) -> dict | None:
    """세션 + 그 세션이 보는 스냅샷 + 저장소 표기. 없으면 None.

    후속 질문에 필요한 context 와 화면에 쓸 display 표기를 한 번에 가져온다.
    owner/name(소문자 정규화 키)도 함께 가져온다 — 코드 인덱싱이 GitHub 을 부를 때
    쓰는 값이라, 없으면 display 표기를 소문자로 바꾸는 추측을 해야 한다.
    """
    with cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT c.id, c.created_at, c.last_message_at,
                   s.id AS snapshot_id, s.context, s.summary, s.model,
                   s.source_bundle,
                   r.owner, r.name,
                   r.display_owner, r.display_name
              FROM chat_sessions c
              JOIN repo_snapshots s ON s.id = c.snapshot_id
              JOIN repos r          ON r.id = s.repo_id
             WHERE c.id = %s
            """,
            (session_id,),
        )
        return cur.fetchone()


def add_exchange(session_id: str, question: str, answer: str) -> None:
    """질문과 답변을 **한 트랜잭션으로** 넣는다.

    따로 넣으면 답변 저장만 실패했을 때 질문이 홀로 남아, 다음 요청의 이력이
    user 로 끝난다. 그러면 LLM 에 보내는 메시지의 역할이 번갈아 나오지 않아 호출이 거부된다.
    """
    with cursor() as cur:
        cur.executemany(
            "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
            [(session_id, "user", question), (session_id, "assistant", answer)],
        )
        cur.execute(
            "UPDATE chat_sessions SET last_message_at = now() WHERE id = %s",
            (session_id,),
        )


# 빈 답변과 그 짝인 질문을 빼고 읽는다. `{order}` 자리만 갈아끼워 두 경로가 함께 쓴다.
#
# **한 쌍으로 뺀다.** assistant 만 빼면 user 가 연속으로 남고, 답을 못 받은 질문만
# 화면과 이력에 남는다.
#
# **거르기를 SQL 안에서 한다.** 파이썬에서 자른 뒤 거르면 limit 이 빈 행까지 세어,
# LLM 에 보내는 이력이 MAX_HISTORY_MESSAGES 보다 짧아진다.
#
# 지금 남아 있는 것은 정확히 '' 뿐이지만 공백만 든 답변까지 잡는다 — 화면에서는 똑같이
# 빈 말풍선이다. `btrim()` 은 인자를 안 주면 **스페이스만** 지워서 줄바꿈을 놓친다.
#
# `coalesce(..., false)` 는 마지막 행 때문이다. 거기서 `lead()` 가 NULL 이라 조건이
# NULL 이 되고, `WHERE NOT NULL` 은 그 행을 **조용히 버린다** — 짝을 못 받은 마지막
# 질문이 그렇게 사라진다.
_LIST_MESSAGES = """
WITH m AS (
  SELECT id, role, content, created_at,
         lead(role)    OVER (ORDER BY id) AS next_role,
         lead(content) OVER (ORDER BY id) AS next_content
    FROM messages WHERE session_id = %s
)
SELECT id, role, content, created_at FROM m
 WHERE NOT (role = 'assistant' AND content ~ '^[[:space:]]*$')
   AND NOT coalesce(
             role = 'user' AND next_role = 'assistant'
                          AND next_content ~ '^[[:space:]]*$',
             false)
 ORDER BY id {order}
"""


def list_messages(session_id: str, limit: int | None = None) -> list[dict]:
    """오래된 순. limit 을 주면 **최근** limit 개만 오래된 순으로 돌려준다.

    LLM 에 보낼 이력을 자를 때는 최근 것을 남겨야 하므로, 뒤에서 잘라서 다시 뒤집는다.

    **빈 답변은 질문과 함께 빠진다.** 예전에 빈 문자열이 그대로 저장된 적이 있고
    (`claude_client.NO_ANSWER` 주석 참고), 그 행들이 지금도 요청마다 이력에 실려 간다.
    막는 쪽이 아니라 읽는 쪽에 두어야 이미 남은 것까지 함께 정리된다.
    """
    with cursor(commit=False) as cur:
        if limit is None:
            cur.execute(_LIST_MESSAGES.format(order=""), (session_id,))
            return cur.fetchall()

        cur.execute(_LIST_MESSAGES.format(order="DESC LIMIT %s"), (session_id, limit))
        return list(reversed(cur.fetchall()))
