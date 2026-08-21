"""색인 빌드 통합 테스트. 실제 PostgreSQL 이 필요하다 (없으면 skip)."""

import re
from pathlib import Path

import pytest

from app.db import index_status
from app.db import repos as repo_db
from app.db.pool import cursor

pytestmark = pytest.mark.usefixtures("db")


def test_chunk_tables_match_the_schema():
    """`CHUNK_TABLES` 가 schema.sql 의 청크 테이블 전부를 담고 있는가.

    **DB 가 없어도 도는 순수 대조다** (fixture 는 파일에 영향을 주지 않는다).

    이 목록이 빠지면 `list_all()` 이 그 테이블의 청크를 못 세서 **화면에 0개로 보인다.**
    색인이 없는 것과, 전체 주입(우회)과, 깨진 색인이 전부 같은 모양이 된다 —
    오류가 나지 않아 눈으로 보기 전까지 모른다. 실제로 그렇게 틀렸다.
    """
    schema = (Path(__file__).resolve().parents[1] / "app" / "db" / "schema.sql").read_text(
        encoding="utf-8"
    )
    in_schema = set(
        re.findall(r"CREATE TABLE IF NOT EXISTS (code_chunks\w*)", schema)
    )
    assert in_schema, "schema.sql 에서 청크 테이블을 못 찾았다 — 정규식을 확인하라"
    assert set(index_status.CHUNK_TABLES) == in_schema, (
        f"CHUNK_TABLES 와 schema.sql 이 다르다."
        f" 목록에만: {set(index_status.CHUNK_TABLES) - in_schema},"
        f" 스키마에만: {in_schema - set(index_status.CHUNK_TABLES)}"
    )

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

TABLE = "code_chunks_1024"


@pytest.fixture
def snapshot_id() -> int:
    return repo_db.put_snapshot(**SNAPSHOT)["id"]


def _add_chunk(build_id: int, snapshot_id: int, table: str = TABLE) -> None:
    with cursor() as cur:
        cur.execute(
            f"""INSERT INTO {table}
                    (build_id, snapshot_id, path, language, start_line, end_line,
                     content, embedding)
                VALUES (%s, %s, 'a.py', 'python', 1, 5, 'print(1)', %s::vector)""",
            (build_id, snapshot_id, [0.0] * 1024),
        )


def test_begin_returns_a_build_and_blocks_a_second_start(snapshot_id):
    """같은 스냅샷을 두 번 인덱싱하면 tarball 도 임베딩도 두 배로 든다."""
    build_id = index_status.begin(snapshot_id, table=TABLE)
    assert build_id is not None
    assert index_status.begin(snapshot_id, table=TABLE) is None

    assert index_status.get(snapshot_id, table=TABLE)["status"] == "running"


def test_completing_activates_the_build(snapshot_id):
    build_id = index_status.begin(snapshot_id, table=TABLE, chunk_rule="abcd1234")
    index_status.complete(build_id, 145)

    assert index_status.is_completed(snapshot_id, table=TABLE) is True
    assert index_status.active_build_id(snapshot_id, table=TABLE) == build_id

    row = index_status.get(snapshot_id, table=TABLE)
    assert (row["status"], row["chunks_total"], row["chunk_rule"]) == (
        "completed", 145, "abcd1234",
    )


def test_a_rebuild_can_start_while_an_index_is_active(snapshot_id):
    """활성 색인이 있어도 다시 만들 수 있어야 한다 — 그게 재색인이다."""
    first = index_status.begin(snapshot_id, table=TABLE)
    index_status.complete(first, 145)

    second = index_status.begin(snapshot_id, table=TABLE)
    assert second is not None and second != first
    # 새 빌드가 끝나기 전까지 검색은 옛 빌드를 계속 본다.
    assert index_status.active_build_id(snapshot_id, table=TABLE) == first


def test_search_keeps_using_the_old_build_until_the_new_one_finishes(snapshot_id):
    """제자리 교체를 하지 않는 이유 — 재색인 40~96분 동안 코드가 사라지면 안 된다."""
    first = index_status.begin(snapshot_id, table=TABLE)
    index_status.complete(first, 1)
    _add_chunk(first, snapshot_id)

    second = index_status.begin(snapshot_id, table=TABLE)
    _add_chunk(second, snapshot_id)  # 새 빌드가 청크를 쌓는 중

    # 아직 활성은 옛 빌드다.
    assert index_status.active_build_id(snapshot_id, table=TABLE) == first

    index_status.complete(second, 1)
    assert index_status.active_build_id(snapshot_id, table=TABLE) == second


def test_empty_repository_stays_completed(snapshot_id):
    """청크 0개(소스가 없는 저장소)도 완료는 완료다.

    청크 존재 여부로 판단하던 시절에는 이런 저장소가 질문마다 다시 인덱싱됐다.
    """
    build_id = index_status.begin(snapshot_id, table=TABLE)
    index_status.complete(build_id, 0)

    assert index_status.is_completed(snapshot_id, table=TABLE) is True


def test_failed_rebuild_keeps_the_previous_index(snapshot_id):
    """재색인이 실패해도 쓰고 있던 색인은 살아 있어야 한다."""
    first = index_status.begin(snapshot_id, table=TABLE)
    index_status.complete(first, 145)

    second = index_status.begin(snapshot_id, table=TABLE)
    index_status.fail(second, "저장소 아카이브가 너무 큽니다 (500MB 초과).")

    assert index_status.active_build_id(snapshot_id, table=TABLE) == first
    assert index_status.is_completed(snapshot_id, table=TABLE) is True
    # 실패한 뒤에는 다시 시도할 수 있다.
    assert index_status.begin(snapshot_id, table=TABLE) is not None


def test_failure_keeps_the_reason(snapshot_id):
    build_id = index_status.begin(snapshot_id, table=TABLE)
    index_status.fail(build_id, "저장소 아카이브가 너무 큽니다 (500MB 초과).")

    row = index_status.get(snapshot_id, table=TABLE)
    assert row["status"] == "failed"
    assert "500MB" in row["error"]
    assert index_status.is_completed(snapshot_id, table=TABLE) is False


def test_progress_is_recorded(snapshot_id):
    build_id = index_status.begin(snapshot_id, table=TABLE)
    index_status.set_total(build_id, 1683)
    index_status.advance(build_id, 320)

    row = index_status.get(snapshot_id, table=TABLE)
    assert (row["chunks_done"], row["chunks_total"]) == (320, 1683)


def test_get_prefers_the_active_build_over_a_running_rebuild(snapshot_id):
    """재색인 중이어도 사용자에게는 '색인 완료'로 보여야 한다.

    진행 중인 빌드를 먼저 돌려주면 화면에 "코드를 처음 읽는 중" 배너가 떠서,
    멀쩡히 답하고 있는데도 준비가 안 된 것처럼 보인다.
    """
    first = index_status.begin(snapshot_id, table=TABLE)
    index_status.complete(first, 145)
    index_status.begin(snapshot_id, table=TABLE)  # 재색인 시작(running)

    row = index_status.get(snapshot_id, table=TABLE)
    assert row["status"] == "completed"
    assert row["build_id"] == first


def test_status_is_per_table(snapshot_id):
    """차원이 다른 모델은 청크 테이블이 갈리므로 진행 상태도 따로 간다."""
    build_id = index_status.begin(snapshot_id, table="code_chunks")
    index_status.complete(build_id, 145)

    assert index_status.is_completed(snapshot_id, table="code_chunks") is True
    assert index_status.is_completed(snapshot_id, table=TABLE) is False


def test_rollback_switches_back_to_an_older_build(snapshot_id):
    """새 색인이 나쁘면 포인터만 되돌려 즉시 복구할 수 있어야 한다."""
    first = index_status.begin(snapshot_id, table=TABLE)
    index_status.complete(first, 145)
    second = index_status.begin(snapshot_id, table=TABLE)
    index_status.complete(second, 236)

    assert index_status.active_build_id(snapshot_id, table=TABLE) == second
    assert index_status.activate(snapshot_id, first, table=TABLE) is True
    assert index_status.active_build_id(snapshot_id, table=TABLE) == first


def test_rollback_refuses_an_unfinished_build(snapshot_id):
    """진행 중인 빌드를 가리키면 절반만 임베딩된 코드로 검색하게 된다."""
    first = index_status.begin(snapshot_id, table=TABLE)
    index_status.complete(first, 145)
    running = index_status.begin(snapshot_id, table=TABLE)

    assert index_status.activate(snapshot_id, running, table=TABLE) is False
    assert index_status.active_build_id(snapshot_id, table=TABLE) == first


def test_prune_keeps_the_active_build_and_one_spare(snapshot_id):
    """롤백 여지를 남기되 무한정 쌓이지는 않게 한다."""
    builds = []
    for n in (1, 2, 3):
        build_id = index_status.begin(snapshot_id, table=TABLE)
        index_status.complete(build_id, n)
        _add_chunk(build_id, snapshot_id)
        builds.append(build_id)

    removed = index_status.prune_builds(snapshot_id, table=TABLE, keep=1)

    assert removed == 1  # 가장 오래된 것 하나
    remaining = [b["build_id"] for b in index_status.list_builds(snapshot_id, table=TABLE)]
    assert remaining == [builds[2], builds[1]]
    # 청크도 함께 사라진다 (ON DELETE CASCADE).
    with cursor(commit=False) as cur:
        cur.execute(f"SELECT count(*) AS n FROM {TABLE} WHERE build_id = %s", (builds[0],))
        assert cur.fetchone()["n"] == 0


def test_prune_never_removes_a_running_build(snapshot_id):
    """지금 누군가 만들고 있는 빌드를 지우면 그 작업이 통째로 날아간다."""
    done = index_status.begin(snapshot_id, table=TABLE)
    index_status.complete(done, 1)
    running = index_status.begin(snapshot_id, table=TABLE)

    index_status.prune_builds(snapshot_id, table=TABLE, keep=0)

    ids = [b["build_id"] for b in index_status.list_builds(snapshot_id, table=TABLE)]
    assert running in ids


def test_stale_finds_indexes_built_with_another_rule(snapshot_id):
    build_id = index_status.begin(snapshot_id, table=TABLE, chunk_rule="oldrule1")
    index_status.complete(build_id, 145)

    stale = index_status.stale("newrule2", table=TABLE)
    assert [row["snapshot_id"] for row in stale] == [snapshot_id]
    assert index_status.stale("oldrule1", table=TABLE) == []


def test_stale_ignores_tables_that_are_not_in_use(snapshot_id):
    """차원이 다른 옛 테이블은 아무도 읽지 않는다 — 신호에 섞이면 진짜 대상이 묻힌다."""
    build_id = index_status.begin(snapshot_id, table="code_chunks", chunk_rule="oldrule1")
    index_status.complete(build_id, 145)

    assert index_status.stale("newrule2", table=TABLE) == []


def test_stale_ignores_unfinished_indexes(snapshot_id):
    """진행 중이거나 실패한 색인은 애초에 쓸 수 없어서 '낡았다'가 의미가 없다."""
    index_status.begin(snapshot_id, table=TABLE, chunk_rule="oldrule1")

    assert index_status.stale("newrule2", table=TABLE) == []


def test_list_all_counts_actual_chunks(snapshot_id):
    """기록된 수가 아니라 실제로 센 값을 보여줘야 한다."""
    build_id = index_status.begin(snapshot_id, table=TABLE)
    index_status.complete(build_id, 999)  # 기록만 999
    _add_chunk(build_id, snapshot_id)

    row = next(
        r for r in index_status.list_all()
        if r["snapshot_id"] == snapshot_id and r["table_name"] == TABLE
    )
    assert (row["chunks_total"], row["chunks_actual"]) == (999, 1)


def test_reset_running_frees_a_killed_indexing(snapshot_id):
    """인덱싱 스레드는 프로세스와 함께 사라진다. running 인 채 남으면 재시도가 영원히 막힌다."""
    index_status.begin(snapshot_id, table=TABLE)

    assert index_status.reset_running() == 1
    assert index_status.get(snapshot_id, table=TABLE)["status"] == "pending"


def test_completed_status_is_backfilled_for_existing_chunks(snapshot_id):
    """이 구조가 생기기 전에 인덱싱을 마친 스냅샷을 다시 인덱싱하면 안 된다.

    schema.sql 의 백필이 그 일을 한다(기동할 때마다 멱등 실행된다).
    """
    with cursor() as cur:
        cur.execute(
            f"""INSERT INTO {TABLE}
                    (snapshot_id, path, language, start_line, end_line, content, embedding)
                VALUES (%s, 'a.py', 'python', 1, 5, 'print(1)', %s::vector)""",
            (snapshot_id, [0.0] * 1024),
        )
        cur.execute(
            """INSERT INTO snapshot_index_status
                   (snapshot_id, table_name, status, chunks_total, chunks_done)
               VALUES (%s, %s, 'completed', 1, 1)""",
            (snapshot_id, TABLE),
        )

    from app.db import pool

    assert pool.init_schema()

    assert index_status.is_completed(snapshot_id, table=TABLE) is True
    build_id = index_status.active_build_id(snapshot_id, table=TABLE)
    with cursor(commit=False) as cur:
        cur.execute(
            f"SELECT count(*) AS n FROM {TABLE} WHERE build_id = %s", (build_id,)
        )
        assert cur.fetchone()["n"] == 1
