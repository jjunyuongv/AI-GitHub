"""repos / repo_snapshots 쿼리.

키를 만드는 규칙(무엇을 소문자화하고 버전을 어디서 뽑는지)은 services/summary_cache.py 가
갖고 있다. 여기서는 이미 만들어진 값을 받아 저장·조회만 한다.
"""

from app.db.pool import cursor


def _upsert_repo(
    cur, *, owner: str, name: str, display_owner: str, display_name: str
) -> int:
    """저장소 행을 만들거나 갱신하고 id 를 돌려준다.

    저장소가 이전·개명되면 정식 표기가 바뀌므로 display_* 는 매번 최신으로 덮어쓴다.
    """
    cur.execute(
        """
        INSERT INTO repos (owner, name, display_owner, display_name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (owner, name) DO UPDATE
           SET display_owner = EXCLUDED.display_owner,
               display_name  = EXCLUDED.display_name,
               last_seen_at  = now()
        RETURNING id
        """,
        (owner, name, display_owner, display_name),
    )
    return cur.fetchone()["id"]


def get_snapshot(*, owner: str, name: str, key_source: str, version: str) -> dict | None:
    """해당 버전의 스냅샷. 없으면 None."""
    with cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT s.id, s.context, s.summary, s.model, s.key_source, s.version,
                   s.source_bundle, s.source_tokens, s.created_at
              FROM repo_snapshots s
              JOIN repos r ON r.id = s.repo_id
             WHERE r.owner = %s AND r.name = %s
               AND s.key_source = %s AND s.version = %s
            """,
            (owner, name, key_source, version),
        )
        return cur.fetchone()


def get_snapshot_repo(snapshot_id: int) -> dict | None:
    """스냅샷이 어느 저장소의 것인지. 없으면 None.

    owner/name 은 소문자 정규화 키다 — GitHub 을 부를 때 쓰는 값이라, 재색인이
    이 값으로 tarball 을 받는다. display_* 는 화면 표기용이다.
    """
    with cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT s.id AS snapshot_id, s.key_source, s.version,
                   r.owner, r.name, r.display_owner, r.display_name
              FROM repo_snapshots s
              JOIN repos r ON r.id = s.repo_id
             WHERE s.id = %s
            """,
            (snapshot_id,),
        )
        return cur.fetchone()


def set_source_bundle(snapshot_id: int, bundle: str, tokens: int) -> None:
    """이 스냅샷을 전체 주입(RAG 우회) 경로로 표시한다.

    /analyze 때는 소스가 아직 없다(tarball 은 백그라운드 색인 작업이 받는다).
    그래서 put_snapshot 이 아니라 그 작업이 나중에 채운다.
    """
    with cursor() as cur:
        cur.execute(
            "UPDATE repo_snapshots SET source_bundle = %s, source_tokens = %s WHERE id = %s",
            (bundle, tokens, snapshot_id),
        )


def put_snapshot(
    *,
    owner: str,
    name: str,
    display_owner: str,
    display_name: str,
    key_source: str,
    version: str,
    context: str,
    summary: str,
    model: str,
) -> dict:
    """스냅샷을 저장한다. 같은 버전이 이미 있으면 내용을 덮어쓴다.

    덮어쓰기는 재인덱싱(같은 pushed_at 인데 프롬프트만 바뀐 경우)을 위한 것이다.
    스냅샷 id 가 유지되므로 진행 중인 대화가 끊기지 않는다.
    """
    with cursor() as cur:
        repo_id = _upsert_repo(
            cur,
            owner=owner,
            name=name,
            display_owner=display_owner,
            display_name=display_name,
        )
        cur.execute(
            """
            INSERT INTO repo_snapshots (repo_id, key_source, version, context, summary, model)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (repo_id, key_source, version) DO UPDATE
               SET context = EXCLUDED.context,
                   summary = EXCLUDED.summary,
                   model   = EXCLUDED.model
            RETURNING id, context, summary, model, key_source, version, created_at
            """,
            (repo_id, key_source, version, context, summary, model),
        )
        return cur.fetchone()
