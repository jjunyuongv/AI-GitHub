"""색인 빌드 쿼리 — 인덱싱 한 번의 생애와 "지금 검색이 보는 빌드".

큰 저장소는 임베딩만 수십 분이 걸려서 인덱싱을 백그라운드로 돌린다. 그러면
"아직 안 했다"와 "하는 중"과 "실패했다"를 구분해야 하는데, 청크 행 존재 여부로는
셋 다 똑같이 '청크 없음'으로 보인다. 그래서 상태를 따로 남긴다.

**빌드를 쌓고 포인터를 바꾼다.** 청크를 제자리에서 갈아끼우면 그 사이(40~96분)
챗봇이 코드 없이 답한다. 새 빌드를 따로 만들어 두고 완료된 순간에
snapshot_index_status.active_build_id 만 옮기면, 그동안 옛 빌드로 계속 답할 수 있다.
포인터를 되돌리면 그대로 롤백이다.

상태는 pending → running → completed | failed 로만 움직인다.
"""

from psycopg import sql

from app.config import CHUNK_TABLE
from app.db.pool import cursor

PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"

# 청크가 들어갈 수 있는 모든 테이블. `list_all()` 이 실제 청크 수를 셀 때 전부 훑는다.
#
# **schema.sql 의 CREATE TABLE 목록과 같아야 한다.** 전에는 이 목록이 SQL 안에 두 개만
# 박혀 있었고, 테이블을 늘렸을 때 여기를 안 고쳐서 **화면이 청크 0개로 보였다**
# (색인이 없는 것처럼, 그리고 전체 주입 스냅샷과 구분되지 않게). 오류가 나지 않아
# 조용히 틀리는 종류라 tests/test_db_index_status.py 가 schema.sql 과 대조해 고정한다.
CHUNK_TABLES = (
    "code_chunks",            # 768, jina-code (미사용)
    "code_chunks_1024",       # 1024, e5-large fp32
    "code_chunks_1024_int8",  # 1024, e5-large int8
    "code_chunks_384",        # 384, e5-small
    "code_chunks_768_e5",     # 768, e5-base
)

# 활성 빌드 말고 몇 개를 더 남길지. 최소 1 이면 직전 빌드가 남아 롤백할 수 있다.
# 0 이면 새 빌드가 활성화되는 순간 옛 청크가 사라져 되돌릴 수 없다.
KEEP_BUILDS = 1


def _table(table: str | None) -> str:
    return table or CHUNK_TABLE


def active_build_id(snapshot_id: int, table: str | None = None) -> int | None:
    """검색이 봐야 할 빌드. 없으면 이 스냅샷은 아직 쓸 수 있는 색인이 없다."""
    with cursor(commit=False) as cur:
        cur.execute(
            """SELECT active_build_id FROM snapshot_index_status
                WHERE snapshot_id = %s AND table_name = %s""",
            (snapshot_id, _table(table)),
        )
        row = cur.fetchone()
        return row["active_build_id"] if row else None


def is_completed(snapshot_id: int, table: str | None = None) -> bool:
    """이 스냅샷을 이 테이블에 인덱싱해 두었는지. 청크가 0개여도 완료는 완료다.

    청크 존재가 아니라 **활성 빌드 유무**로 판단한다 — 소스가 없는 저장소(청크 0개)를
    질문마다 다시 인덱싱하던 버그가 그래서 났다.
    """
    return active_build_id(snapshot_id, table) is not None


def get(snapshot_id: int, table: str | None = None) -> dict | None:
    """**사용자에게 보여줄** 색인 상태. 없으면 None.

    활성 빌드가 있으면 그것을 돌려준다 — 재색인이 도는 중이어도 사용자 입장에서는
    색인이 완료돼 있다(검색은 활성 빌드를 쓴다). 진행 중인 빌드를 먼저 돌려주면
    화면에 "코드를 처음 읽는 중" 배너가 떠서, 멀쩡히 답하고 있는데도 아직 준비가
    안 된 것처럼 보인다.

    활성 빌드가 없을 때만 최신 빌드(진행 중이거나 실패한 것)를 돌려준다.
    빌드 이력 전체는 list_builds() 가 답한다.
    """
    with cursor(commit=False) as cur:
        cur.execute(
            """SELECT b.id AS build_id, b.snapshot_id, b.table_name, b.status,
                      b.chunks_total, b.chunks_done, b.error, b.started_at, b.updated_at,
                      b.chunk_rule,
                      (s.active_build_id = b.id) AS is_active
                 FROM index_builds b
                 LEFT JOIN snapshot_index_status s
                        ON s.snapshot_id = b.snapshot_id AND s.table_name = b.table_name
                WHERE b.snapshot_id = %s AND b.table_name = %s
                ORDER BY (s.active_build_id = b.id) DESC NULLS LAST, b.id DESC
                LIMIT 1""",
            (snapshot_id, _table(table)),
        )
        return cur.fetchone()


def begin(snapshot_id: int, table: str | None = None, chunk_rule: str = "") -> int | None:
    """새 빌드를 시작한다. 시작했으면 build_id, 이미 진행 중이면 None.

    **활성 빌드가 있어도 시작할 수 있다** — 그것이 재색인이다. 막는 것은 같은 대상에
    이미 진행 중인 빌드가 있는 경우뿐이고, 그 판정과 삽입을 한 문장으로 한다
    (조회 후 삽입으로 나누면 동시 요청 둘이 함께 시작할 수 있다).
    """
    with cursor() as cur:
        cur.execute(
            """INSERT INTO index_builds
                   (snapshot_id, table_name, chunk_rule, status, started_at, updated_at)
               SELECT %s, %s, %s, 'running', now(), now()
                WHERE NOT EXISTS (
                      SELECT 1 FROM index_builds
                       WHERE snapshot_id = %s AND table_name = %s
                         AND status IN ('pending', 'running'))
               RETURNING id""",
            (snapshot_id, _table(table), chunk_rule, snapshot_id, _table(table)),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def set_total(build_id: int, total: int) -> None:
    """청크 수가 확정됐을 때(=임베딩 직전) 부른다.

    **started_at 을 여기서 다시 찍는다.** 남은 시간은 '경과 / 끝난 청크'로 계산하는데,
    begin() 시점부터 재면 수집(15~20초)과 청킹 시간이 청크당 속도에 섞여 남은 시간이
    두 배로 부풀려진다 (실측: 실제 29분짜리 작업이 58분으로 나왔다).
    """
    with cursor() as cur:
        cur.execute(
            """UPDATE index_builds
                  SET chunks_total = %s, started_at = now(), updated_at = now()
                WHERE id = %s""",
            (total, build_id),
        )


def advance(build_id: int, done: int) -> None:
    """지금까지 임베딩한 청크 수를 기록한다 (누적값을 그대로 넣는다)."""
    with cursor() as cur:
        cur.execute(
            "UPDATE index_builds SET chunks_done = %s, updated_at = now() WHERE id = %s",
            (done, build_id),
        )


def complete(build_id: int, chunks: int) -> None:
    """빌드를 완료로 표시하고 **검색 포인터를 이 빌드로 옮긴다.**

    포인터 교체까지 한 트랜잭션이다 — 완료로 표시만 하고 포인터가 안 옮겨가면
    새 청크는 아무도 보지 않는 채로 쌓이고, 반대면 미완성 빌드를 검색하게 된다.

    chunks 는 실제로 저장된 청크 수다. 이 값이 곧 화면의 청크 수가 되므로
    호출부가 추정치를 넣으면 안 된다.
    """
    with cursor() as cur:
        cur.execute(
            """UPDATE index_builds
                  SET status = 'completed', chunks_total = %s, chunks_done = %s,
                      error = NULL, updated_at = now(), completed_at = now()
                WHERE id = %s
               RETURNING snapshot_id, table_name""",
            (chunks, chunks, build_id),
        )
        row = cur.fetchone()
        if row is None:
            return
        cur.execute(
            """INSERT INTO snapshot_index_status
                   (snapshot_id, table_name, status, chunks_total, chunks_done,
                    started_at, updated_at, active_build_id)
               VALUES (%s, %s, 'completed', %s, %s, now(), now(), %s)
               ON CONFLICT (snapshot_id, table_name) DO UPDATE
                  SET active_build_id = EXCLUDED.active_build_id,
                      status = 'completed', chunks_total = EXCLUDED.chunks_total,
                      chunks_done = EXCLUDED.chunks_done, updated_at = now()""",
            (row["snapshot_id"], row["table_name"], chunks, chunks, build_id),
        )


def fail(build_id: int, error: str) -> None:
    """실패로 표시하고 사유를 남긴다. 사유는 화면에 그대로 보여준다.

    **활성 포인터는 건드리지 않는다** — 재색인이 실패해도 쓰고 있던 색인은 그대로 살아 있다.
    """
    with cursor() as cur:
        cur.execute(
            """UPDATE index_builds
                  SET status = 'failed', error = %s, updated_at = now()
                WHERE id = %s""",
            (error, build_id),
        )


def activate(snapshot_id: int, build_id: int, table: str | None = None) -> bool:
    """검색 포인터를 이 빌드로 바꾼다 (롤백용). 성공하면 True.

    완료된 빌드만 가리킬 수 있다 — 진행 중인 빌드를 가리키면 절반만 임베딩된 코드로
    검색하게 되고, 아직 없는 코드가 '저장소에 없는 코드'처럼 보인다.
    """
    with cursor() as cur:
        cur.execute(
            """UPDATE snapshot_index_status s
                  SET active_build_id = b.id, updated_at = now()
                 FROM index_builds b
                WHERE b.id = %s AND b.snapshot_id = %s AND b.status = 'completed'
                  AND s.snapshot_id = b.snapshot_id AND s.table_name = b.table_name
               RETURNING s.active_build_id""",
            (build_id, snapshot_id),
        )
        return cur.fetchone() is not None


def prune_builds(snapshot_id: int, table: str | None = None, keep: int = KEEP_BUILDS) -> int:
    """활성 빌드와 최근 keep 개를 남기고 나머지를 지운다. 지운 빌드 수를 반환.

    청크는 build_id 의 ON DELETE CASCADE 로 함께 사라진다.
    진행 중인 빌드는 지우지 않는다 — 그건 지금 누군가 쓰고 있는 작업이다.
    """
    with cursor() as cur:
        cur.execute(
            """DELETE FROM index_builds
                WHERE id IN (
                      SELECT b.id
                        FROM index_builds b
                        LEFT JOIN snapshot_index_status s
                               ON s.snapshot_id = b.snapshot_id
                              AND s.table_name = b.table_name
                       WHERE b.snapshot_id = %s AND b.table_name = %s
                         AND b.status IN ('completed', 'failed')
                         AND (s.active_build_id IS NULL OR b.id <> s.active_build_id)
                       ORDER BY b.id DESC
                      OFFSET %s)""",
            (snapshot_id, _table(table), keep),
        )
        return cur.rowcount


def list_builds(snapshot_id: int, table: str | None = None, limit: int = 20) -> list[dict]:
    """이 스냅샷의 빌드 이력 (최신순). 롤백할 대상을 고를 때 쓴다."""
    with cursor(commit=False) as cur:
        cur.execute(
            """SELECT b.id AS build_id, b.table_name, b.chunk_rule, b.status,
                      b.chunks_total, b.chunks_done, b.error,
                      b.started_at, b.updated_at, b.completed_at,
                      (s.active_build_id = b.id) AS is_active
                 FROM index_builds b
                 LEFT JOIN snapshot_index_status s
                        ON s.snapshot_id = b.snapshot_id AND s.table_name = b.table_name
                WHERE b.snapshot_id = %s AND b.table_name = %s
                ORDER BY b.id DESC
                LIMIT %s""",
            (snapshot_id, _table(table), limit),
        )
        return cur.fetchall()


def list_all() -> list[dict]:
    """활성 색인 전체 + 어느 저장소의 어느 스냅샷인지. 관리자 화면·기동 점검용.

    **full_injection 을 함께 준다.** 우회한 스냅샷은 청크가 0개인데, 그것만 보면
    소스가 없는 저장소나 깨진 색인과 구분되지 않는다 — 화면에서 실제로 헷갈렸다.

    저장소 수만큼만 나오는 목록이라 페이지네이션을 두지 않았다.

    **chunks_actual 은 청크 테이블을 실제로 센 값이다.** 기록된 수와 어긋날 수 있어서
    (기록만 하고 저장에 실패하는 경로가 있을 수 있다) 화면에는 실제 값을 보여준다.

    세는 대상은 `CHUNK_TABLES` 전부다. 전에는 SQL 안에 테이블 이름 둘이 박혀 있었는데,
    테이블을 늘렸을 때 그걸 안 고쳐 **모든 새 색인이 청크 0개로 보였다.**
    """
    counted = sql.SQL(" UNION ALL ").join(
        sql.SQL(
            "SELECT build_id, count(*) AS n FROM {} WHERE build_id IS NOT NULL"
            " GROUP BY build_id"
        ).format(sql.Identifier(name))
        for name in CHUNK_TABLES
    )
    with cursor(commit=False) as cur:
        cur.execute(
            sql.SQL(
            """WITH counted AS ({counted})
               SELECT b.snapshot_id, b.table_name, b.status, b.chunks_total, b.chunks_done,
                      b.error, b.updated_at, b.chunk_rule, b.id AS build_id,
                      COALESCE(c.n, 0) AS chunks_actual,
                      r.display_owner, r.display_name, r.owner, r.name,
                      snap.key_source, snap.version, snap.created_at,
                      snap.source_tokens,
                      (snap.source_bundle IS NOT NULL) AS full_injection
                 FROM snapshot_index_status s
                 JOIN index_builds b ON b.id = s.active_build_id
                 JOIN repo_snapshots snap ON snap.id = b.snapshot_id
                 JOIN repos r ON r.id = snap.repo_id
                 LEFT JOIN counted c ON c.build_id = b.id
                ORDER BY r.owner, r.name, b.snapshot_id, b.table_name"""
            ).format(counted=counted)
        )
        return cur.fetchall()


def stale(current_rule: str, table: str | None = None) -> list[dict]:
    """지금 규칙과 다른 규칙으로 만들어진 활성 색인. 재색인 대상이다.

    **지금 쓰는 청크 테이블만 본다.** 차원이 다른 옛 테이블(모델을 바꾸기 전에 쓰던 것)은
    아무도 읽지 않으므로 낡았든 아니든 고칠 이유가 없다 — 신호에 섞이면 진짜 대상이 묻힌다.
    """
    target = _table(table)
    return [
        row for row in list_all()
        if row["table_name"] == target and row["chunk_rule"] != current_rule
    ]


def reset_running() -> int:
    """남아 있는 running 빌드를 pending 으로 되돌린다. 되돌린 행 수를 반환.

    인덱싱 스레드는 프로세스와 함께 사라지므로, 서버가 내려가면 그 빌드는 영원히
    running 으로 남아 재시도를 막는다. 기동할 때(main.py lifespan) 한 번 정리한다.

    **되돌리기만 하고 큐에 넣지 않는다** — 배포 직후 모든 저장소가 한꺼번에 인덱싱을
    시작하면 그게 곧 장애다. 다시 시작할지는 사람이 정한다.

    **단일 프로세스 전제다.** `uvicorn --workers 2` 이상이면 다른 워커가 인덱싱 중인
    빌드까지 되돌려 중복 인덱싱이 생긴다 (rate_limit 과 같은 전제).
    """
    with cursor() as cur:
        cur.execute(
            "UPDATE index_builds SET status = 'pending', updated_at = now() "
            "WHERE status = 'running'"
        )
        return cur.rowcount
