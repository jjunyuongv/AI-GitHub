"""DB 통합 테스트용 픽스처.

DATABASE_URL 이 없거나 서버에 붙지 못하면 해당 테스트는 skip 한다 —
DB 없이도 나머지 테스트는 전부 돌아야 한다.

테스트는 **별도 데이터베이스**(<dbname>_test)를 쓴다. 개발용 DB 를 TRUNCATE 하면
직접 만들어 본 대화 이력이 매번 지워진다.
"""

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.db import pool


OPT_IN_MARKERS = {
    "evaluation": (
        "검색 품질 측정. 네트워크와 임베딩이 필요해 오래 걸리므로"
        " `-m evaluation` 을 명시했을 때만 돈다.",
        "검색 품질 측정은 `-m evaluation` 으로만 실행합니다",
    ),
    "billed": (
        "Claude 실호출이 있어 **과금되는** 측정. `-m billed` 를 명시했을 때만 돈다.",
        "과금되는 측정은 `-m billed` 로만 실행합니다",
    ),
}


def pytest_configure(config):
    for name, (help_text, _) in OPT_IN_MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {help_text}")


def pytest_collection_modifyitems(config, items):
    """측정 테스트는 기본 실행에서 뺀다.

    일반 pytest 한 번에 수 분이 걸리면 아무도 테스트를 안 돌리게 된다.
    `billed` 는 그 위에 돈까지 든다 — 실수로 도는 일이 없어야 한다.
    """
    requested = config.option.markexpr or ""
    for name, (_, reason) in OPT_IN_MARKERS.items():
        if name in requested:
            continue
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if name in item.keywords:
                item.add_marker(skip)


def _swap_dbname(dsn: str, dbname: str) -> str:
    params = conninfo_to_dict(dsn)
    params["dbname"] = dbname
    return make_conninfo(**params)


def _ensure_database(dsn: str) -> None:
    """테스트 DB 가 없으면 만든다. CREATE DATABASE 는 트랜잭션 안에서 못 돌아 autocommit 으로."""
    target = conninfo_to_dict(dsn)["dbname"]
    with psycopg.connect(
        _swap_dbname(dsn, "postgres"),
        autocommit=True,
        connect_timeout=pool.CONNECT_TIMEOUT_SECONDS,
    ) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (target,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{target}"')


@pytest.fixture(scope="session")
def db_dsn() -> str:
    if not pool.DATABASE_URL:
        pytest.skip("DATABASE_URL 이 없어 DB 통합 테스트를 건너뜁니다.")
    dsn = _swap_dbname(
        pool.DATABASE_URL, conninfo_to_dict(pool.DATABASE_URL)["dbname"] + "_test"
    )
    try:
        _ensure_database(dsn)
    except psycopg.Error as e:
        pytest.skip(f"PostgreSQL 에 붙을 수 없어 건너뜁니다: {e}")
    return dsn


@pytest.fixture
def db(db_dsn, monkeypatch):
    """테스트 DB 로 갈아끼우고 테이블을 비운다. repos 를 지우면 나머지는 CASCADE 로 따라간다.

    사용량·남용 방지 테이블은 repos 에 매여 있지 않아 **따로 비운다** —
    CASCADE 를 믿고 빠뜨리면 앞선 테스트의 카운터가 남아 상한 테스트가 흔들린다.

    `users` 도 같은 이유로 여기 있다. 그쪽은 CASCADE 로 `logins` 와
    `rate_limit_user_daily` 를 함께 데려간다 — 사용자별 상한 테스트가 앞선 테스트의
    카운터를 물려받으면 조용히 흔들린다.
    """
    monkeypatch.setattr(pool, "DATABASE_URL", db_dsn)
    pool.close()  # 다른 DSN 으로 열려 있던 풀은 버린다
    assert pool.init_schema()
    with pool.cursor() as cur:
        cur.execute("TRUNCATE repos CASCADE")
        cur.execute("TRUNCATE runs, rate_limit_daily, rate_limit_hits")
        cur.execute("TRUNCATE users CASCADE")
    yield
    pool.close()
