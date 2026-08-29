"""쌓인 것들을 정리한다. **기본은 dry-run** — 무엇이 지워질지 먼저 보여준다.

지우는 것은 되돌릴 수 없고, 이 중 몇 가지는 사람이 만든 대화가 걸려 있다.
그래서 세는 것과 지우는 것을 같은 함수로 하되 apply 로만 실제 삭제가 일어나게 했다.

**대화가 참조하는 것은 절대 지우지 않는다.** 스냅샷을 지우면 그 세션이 볼 코드와
컨텍스트가 사라져 후속 질문이 답을 못 한다.
"""

import logging

from app.config import CHUNK_TABLE
from app.db import chunks as chunk_store
from app.db import users
from app.db.index_status import CHUNK_TABLES as ALL_CHUNK_TABLES
from app.db.pool import cursor

logger = logging.getLogger(__name__)

# 청크 테이블 목록은 index_status 에서 가져온다 — **같은 목록이 두 곳에 있으면 어긋난다.**
# 실제로 어긋났다: 테이블을 셋 늘렸을 때 여기도 저기도 안 고쳐서, 화면은 청크를
# 0개로 세고 정리 기능은 새 테이블을 아예 못 봤다.
# schema.sql 과의 일치는 tests/test_db_index_status.py 가 지킨다.

# 메시지 없는 세션을 지우기 전에 기다리는 시간.
# **0 으로 두면 안 된다** — /analyze 는 분석할 때마다 세션을 만들고 사용자는 요약을
# 읽은 뒤에 첫 질문을 한다. 그 사이에 지우면 질문하는 순간 세션이 없어진다.
EMPTY_SESSION_GRACE_HOURS = 24


def _unused_tables() -> list[str]:
    return [t for t in ALL_CHUNK_TABLES if t != CHUNK_TABLE]


def survey() -> dict:
    """무엇이 얼마나 쌓였는지 센다. 아무것도 지우지 않는다."""
    report: dict = {"chunk_table_in_use": CHUNK_TABLE}

    with cursor(commit=False) as cur:
        # 1. 지금 쓰지 않는 차원 테이블의 청크. 모델을 바꾸면 그 전 테이블은 아무도 읽지 않는다.
        unused = {}
        for table in _unused_tables():
            cur.execute(f"SELECT count(*) AS n FROM {table}")  # noqa: S608 - 고정 목록
            unused[table] = cur.fetchone()["n"]
        report["unused_table_chunks"] = unused

        # 2. 활성도 아니고 보관 대상도 아닌 빌드. 실제 삭제는 인덱싱이 끝날 때
        #    prune_builds() 가 하므로, 여기서는 남은 것만 센다.
        cur.execute(
            """SELECT count(*) AS n
                 FROM index_builds b
                 LEFT JOIN snapshot_index_status s
                        ON s.snapshot_id = b.snapshot_id AND s.table_name = b.table_name
                WHERE b.status IN ('completed', 'failed')
                  AND (s.active_build_id IS NULL OR b.id <> s.active_build_id)"""
        )
        report["inactive_builds"] = cur.fetchone()["n"]

        # 3. 메시지가 하나도 없는 오래된 세션.
        cur.execute(
            """SELECT count(*) AS n FROM chat_sessions s
                WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)
                  AND s.created_at < now() - make_interval(hours => %s)""",
            (EMPTY_SESSION_GRACE_HOURS,),
        )
        report["empty_sessions"] = cur.fetchone()["n"]

        # 4. 만료된 로그인. **읽는 쪽이 이미 거르므로 남아 있어도 틀리지 않는다**
        #    (users.get_login 이 expires_at 을 SQL 로 본다). 여기 있는 것은 순전히
        #    쌓이지 않게 하려는 것이라, 다른 항목들과 달리 "안 지우면 조용히 틀린다"
        #    는 성격이 아니다.
        cur.execute("SELECT count(*) AS n FROM logins WHERE expires_at <= now()")
        report["expired_logins"] = cur.fetchone()["n"]

        # 5. 아무 대화도 참조하지 않고, 그 저장소의 최신도 아닌 스냅샷.
        #    최신을 남기는 이유: 다음 분석이 그것을 캐시로 쓴다(요약 재사용).
        cur.execute(_ORPHAN_SNAPSHOT_SQL.format(select="count(*) AS n"))
        report["orphan_snapshots"] = cur.fetchone()["n"]

    return report


# 참조 없는 스냅샷을 고르는 조건. 세는 것과 지우는 것이 **같은 조건**이어야 하므로
# 한 곳에 둔다 (dry-run 이 보여준 것과 다른 것이 지워지면 안 된다).
_ORPHAN_SNAPSHOT_SQL = """
    SELECT {select} FROM repo_snapshots snap
     WHERE NOT EXISTS (
           SELECT 1 FROM chat_sessions cs WHERE cs.snapshot_id = snap.id)
       AND snap.id <> (
           SELECT max(newest.id) FROM repo_snapshots newest
            WHERE newest.repo_id = snap.repo_id)
"""


def run(apply: bool = False) -> dict:
    """정리 결과를 돌려준다. apply=False 면 세기만 한다.

    지운 뒤에도 같은 모양의 보고서를 준다 — 무엇을 지웠는지가 곧 이전에 무엇이
    있었는지이므로, 실행 전후를 같은 형식으로 비교할 수 있다.
    """
    before = survey()
    if not apply:
        return {"applied": False, "found": before, "deleted": {}}

    deleted: dict = {}

    # 쓰지 않는 차원 테이블부터. 청크만 지우고 테이블은 남긴다 — 되돌리려면
    # 스키마가 그대로 있어야 하고, 빈 테이블은 비용이 거의 없다.
    deleted["unused_table_chunks"] = {
        table: chunk_store.delete_unused_table(table) for table in _unused_tables()
    }

    # 만료된 로그인. **살아 있는 로그인은 건드리지 않는다** — 여기서 조건을 넓히면
    # 정리가 돌 때마다 모두가 로그아웃된다(tests/test_db_users.py 가 양쪽을 고정한다).
    deleted["expired_logins"] = users.delete_expired()

    with cursor() as cur:
        cur.execute(
            """DELETE FROM chat_sessions s
                WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)
                  AND s.created_at < now() - make_interval(hours => %s)""",
            (EMPTY_SESSION_GRACE_HOURS,),
        )
        deleted["empty_sessions"] = cur.rowcount

        cur.execute(
            f"DELETE FROM repo_snapshots WHERE id IN ({_ORPHAN_SNAPSHOT_SQL.format(select='snap.id')})"
        )
        deleted["orphan_snapshots"] = cur.rowcount

    logger.info("저장소 정리 완료: %s", deleted)
    return {"applied": True, "found": before, "deleted": deleted, "after": survey()}
