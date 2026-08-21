"""code_chunks 쿼리 — 코드 청크 저장과 유사도 검색.

청크는 저장소가 아니라 **스냅샷**에 매달린다. 대화 세션이 보는 코드 버전은
chat_sessions.snapshot_id 로 고정돼 있으므로, 저장소가 갱신돼 새 스냅샷이 생겨도
진행 중인 대화는 자기가 인덱싱한 코드를 계속 본다.

**테이블이 여러 개인 이유**: pgvector 의 vector(N) 은 차원이 고정이라 768 차원 모델과
1024 차원 모델을 한 테이블에 담을 수 없다. 모델을 바꿔 A/B 하려면 차원별 테이블이 필요해서
모든 함수가 table 을 받는다. 기본값은 config.CHUNK_TABLE 이다.
"""

from psycopg import sql

from app.config import CHUNK_TABLE
from app.db.pool import cursor


def _table(name: str | None) -> sql.Identifier:
    """테이블 이름을 식별자로. 문자열 연결 대신 Identifier 로 감싼다."""
    return sql.Identifier(name or CHUNK_TABLE)


# 인덱싱 완료 여부는 여기가 아니라 index_status.is_completed() 가 답한다 —
# 청크 행 존재로 보면 청크가 0개인 경우(소스가 없거나 수집이 실패한 저장소)를
# 질문마다 다시 인덱싱한다. 실제로 그 버그를 겪었다.


def insert_chunks(
    build_id: int,
    snapshot_id: int,
    chunks: list[dict],
    embeddings: list[list[float]],
    table: str | None = None,
) -> int:
    """이 빌드의 청크를 넣는다. **기존 청크는 지우지 않는다.**

    제자리 교체(DELETE 후 INSERT)를 하지 않는 것이 핵심이다 — 그러면 큰 저장소 기준
    40~96분 동안 청크가 없어 챗봇이 코드 없이 답한다. 새 빌드로 쌓아 두고
    index_status.complete() 가 포인터를 옮기는 순간부터 이 청크가 쓰인다.

    삽입과 시각 기록을 한 트랜잭션으로 한다. 중간에 실패하면 전부 되돌아가므로
    '반쯤 들어간 빌드'가 남지 않는다.
    """
    target = _table(table)
    with cursor() as cur:
        if chunks:
            cur.executemany(
                sql.SQL(
                    """INSERT INTO {}
                       (build_id, snapshot_id, path, language,
                        start_line, end_line, content, embedding)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)"""
                ).format(target),
                [
                    (
                        build_id,
                        snapshot_id,
                        chunk["path"],
                        chunk["language"],
                        chunk["start_line"],
                        chunk["end_line"],
                        chunk["content"],
                        embedding,
                    )
                    for chunk, embedding in zip(chunks, embeddings)
                ],
            )
        cur.execute(
            "UPDATE repo_snapshots SET indexed_at = now() WHERE id = %s", (snapshot_id,)
        )
    return len(chunks)


def search(
    build_id: int,
    query_embedding: list[float],
    limit: int = 8,
    table: str | None = None,
) -> list[dict]:
    """질문 벡터와 가까운 청크를 가까운 순으로. **한 빌드 안에서만** 찾는다.

    스냅샷이 아니라 빌드로 찾는 이유: 재색인 중에는 같은 스냅샷에 옛 빌드와 새 빌드의
    청크가 함께 있다. 스냅샷으로 찾으면 절반만 임베딩된 새 청크가 섞여 들어온다.

    거리 연산자는 <=> (코사인). 벡터 크기가 아니라 방향만 보므로 청크 길이가 달라도
    공정하게 비교된다.

    ::vector 캐스트는 생략할 수 없다 — 파이썬 list 는 float8[] 로 전송되고
    <=> 연산자는 vector 끼리만 정의돼 있어서 캐스트 없이는 UndefinedFunction 이 난다
    (register_vector 를 등록해도 그렇다. 그건 numpy 배열과 결과 파싱을 다룬다).
    """
    with cursor(commit=False) as cur:
        cur.execute(
            sql.SQL(
                """SELECT path, language, start_line, end_line, content,
                          embedding <=> %s::vector AS distance
                     FROM {}
                    WHERE build_id = %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s"""
            ).format(_table(table)),
            (query_embedding, build_id, query_embedding, limit),
        )
        return cur.fetchall()


def count(build_id: int, table: str | None = None) -> int:
    with cursor(commit=False) as cur:
        cur.execute(
            sql.SQL("SELECT count(*) AS n FROM {} WHERE build_id = %s").format(
                _table(table)
            ),
            (build_id,),
        )
        return cur.fetchone()["n"]


def delete_unused_table(table: str) -> int:
    """지금 쓰지 않는 차원 테이블의 청크를 비운다. 지운 행 수를 반환.

    모델을 바꾸면 차원이 달라져 테이블이 갈리는데(vector(N) 은 차원 고정), 옛 테이블은
    아무도 읽지 않은 채 남는다. 되돌릴 여지로 남겨 두는 것도 방법이지만, 그 인덱스는
    옛 청킹 규칙으로 만들어져 있어서 되돌려도 어차피 다시 만들어야 한다.
    """
    if table == (CHUNK_TABLE or ""):
        raise ValueError(f"지금 쓰는 테이블({table})은 비울 수 없습니다.")
    with cursor() as cur:
        cur.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
        return cur.rowcount
