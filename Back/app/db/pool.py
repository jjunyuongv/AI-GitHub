"""PostgreSQL 연결 풀.

DATABASE_URL 이 비어 있으면 풀을 만들지 않는다. 그때는 is_enabled() 가 False 이고
호출부는 DB 없이 동작하는 경로로 빠진다 (요약 캐시 꺼짐, /chat 은 503).

풀 생성은 처음 쓸 때까지 미룬다 — import 시점에 접속하면 DB 없이 도는
단위 테스트와 스크립트가 전부 막힌다.
"""

import atexit
import logging
import threading
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import DATABASE_URL

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# DB 가 응답하지 않을 때 요청을 붙잡아 두는 시간. 짧게 잡아 실패로 떨어뜨린다 —
# 기본값(접속 무제한 대기 / 풀 30초)이면 DB 가 죽었을 때 /analyze 가 몇 분씩 매달린다.
# 방화벽이 SYN 을 응답 없이 버리는 주소로는 connect_timeout 이 유일한 탈출구다.
CONNECT_TIMEOUT_SECONDS = 5
POOL_TIMEOUT_SECONDS = 5

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


class DatabaseUnavailable(Exception):
    """DB 를 쓸 수 없다. API 계층이 503 으로 바꾼다."""


# DB 쪽에서 올라올 수 있는 예외 전부. 풀 예외(PoolTimeout 등)도 psycopg.Error 하위다.
# 호출부는 이걸로 잡아서 "DB 없이 진행" 또는 503 으로 바꾼다.
DB_ERRORS = (DatabaseUnavailable, psycopg.Error)


def is_enabled() -> bool:
    return bool(DATABASE_URL)


def _configure(conn: psycopg.Connection) -> None:
    """새 연결마다 vector 타입 어댑터를 등록한다.

    등록해 두면 list[float] 를 그대로 파라미터로 넘길 수 있다. 없으면 768개 실수를
    '[0.1,0.2,...]' 문자열로 직렬화해 ::vector 로 캐스트해야 해서 느리고 지저분하다.

    vector 확장이 없는 DB(공식 postgres 이미지 등)에서도 앱은 떠야 하므로 실패는 삼킨다
    — 그 경우 RAG 쿼리만 실패하고 요약·대화는 그대로 동작한다.
    """
    try:
        from pgvector.psycopg import register_vector

        register_vector(conn)
    except Exception as e:
        logger.debug("vector 어댑터를 등록하지 못했습니다 (RAG 기능만 영향): %s", e)


def get_pool() -> ConnectionPool:
    global _pool
    if not is_enabled():
        raise DatabaseUnavailable(
            "DATABASE_URL 이 설정되지 않았습니다. Back/.env 에 접속 문자열을 넣고 서버를 재시작하세요."
        )
    with _pool_lock:
        if _pool is None:
            # open=False 로 만들고 곧바로 open() 한다. 생성 시점에 접속을 기다리지 않으므로
            # DB 가 아직 안 떠 있어도 앱은 뜬다 (쿼리 시점에 실패한다).
            _pool = ConnectionPool(
                DATABASE_URL,
                min_size=1,
                max_size=5,
                timeout=POOL_TIMEOUT_SECONDS,
                kwargs={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
                configure=_configure,
                open=False,
            )
            _pool.open()
    return _pool


@contextmanager
def cursor(commit: bool = True):
    """dict 를 돌려주는 커서. 기존 코드가 전부 dict 를 다루므로 row_factory 를 맞춰 둔다."""
    with get_pool().connection() as conn:
        conn.autocommit = False
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur
        if commit:
            conn.commit()
        else:
            conn.rollback()


def init_schema() -> bool:
    """schema.sql 을 실행한다. 실패하면 경고만 남기고 False.

    DB 장애가 앱 기동 자체를 막지 않게 한다 — /health 와 (캐시 없는) /analyze 는
    DB 없이도 동작해야 한다.
    """
    if not is_enabled():
        logger.warning("DATABASE_URL 이 없어 DB 기능을 끕니다 (요약 캐시·대화 기능 비활성).")
        return False
    try:
        with cursor() as cur:
            cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    except DB_ERRORS as e:
        logger.warning("스키마를 적용하지 못했습니다: %s", e)
        return False
    logger.info("DB 스키마 적용 완료.")
    return True


def close() -> None:
    """앱 종료 시 풀을 닫는다. 두 번 불러도 안전하다."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


# 서버는 lifespan 에서 close() 를 부르지만, 스크립트·테스트는 그럴 곳이 없다.
# 풀을 열어 둔 채로 인터프리터가 끝나면 psycopg_pool 이 종료 시점에
# 워커 스레드를 join 하려다 PythonFinalizationError 를 뱉는다.
atexit.register(close)
