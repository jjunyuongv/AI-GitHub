"""snapshot_source_files 쿼리 — 수집한 소스 파일의 원문 보관.

**청크와 다른 것을 담는다.** code_chunks 는 검색용으로 잘라 놓은 조각이고 여기는
자르기 전의 원본이다. 청크를 이어붙여 원본을 만들 수 없어서 따로 둔다 — 청킹이
import 노드를 건너뛰고(chunker.chunk_file), 정의 사이의 틈을 버리고(_node_chunks),
40자 미만 조각을 지운다(_merge_small). 실측에서 비어있지 않은 줄의 8.5~12.7% 가
사라졌고, 반대로 OVERLAP_LINES 는 같은 줄을 중복시킨다. 부분집합도 상위집합도 아니다.

청크와 마찬가지로 **스냅샷**에 매단다. 세션이 보는 코드 버전은 chat_sessions.snapshot_id
로 확정돼 있으므로, 저장소가 갱신돼 새 스냅샷이 생겨도 진행 중인 대화는 자기가 보던
파일을 계속 읽는다.

여기 있는 것은 보관·조회의 최소 표면이다. read_file/grep 같은 도구는 이것을 쓰는
쪽에서 만든다.
"""

from app.db.pool import cursor


def put_files(snapshot_id: int, files: dict[str, str]) -> int:
    """이 스냅샷의 소스를 통째로 갈아끼운다. 넣은 파일 수를 반환.

    **제자리 교체다 (DELETE 후 INSERT, 한 트랜잭션).** 청크가 빌드를 쌓고 포인터를
    옮기는 것과 다른데, 이유는 여기 담기는 것이 빌드마다 달라지지 않기 때문이다 —
    같은 스냅샷은 같은 시점의 저장소이므로 재색인해도 같은 소스가 들어온다.
    청킹 규칙이 바뀌어도 이 표는 그대로다.

    upsert 로 하지 않는 이유: 파일이 줄어든 경우(수집 상한이 내려갔거나 강제 푸시로
    파일이 사라진 경우) 옛 행이 남는다. 그러면 도구가 저장소에 없는 파일을 읽어 준다.

    한 트랜잭션이라 반쯤 갈린 상태는 읽는 쪽에 보이지 않는다.
    """
    with cursor() as cur:
        cur.execute(
            "DELETE FROM snapshot_source_files WHERE snapshot_id = %s", (snapshot_id,)
        )
        if files:
            cur.executemany(
                """INSERT INTO snapshot_source_files (snapshot_id, path, content)
                   VALUES (%s, %s, %s)""",
                [(snapshot_id, path, content) for path, content in files.items()],
            )
    return len(files)


def get_file(snapshot_id: int, path: str) -> str | None:
    """파일 하나의 원문. 보관돼 있지 않으면 None.

    PK 가 (snapshot_id, path) 라 한 행만 읽는다 — 저장소 전체를 메모리에 올리지 않는다.
    """
    with cursor(commit=False) as cur:
        cur.execute(
            "SELECT content FROM snapshot_source_files"
            " WHERE snapshot_id = %s AND path = %s",
            (snapshot_id, path),
        )
        row = cur.fetchone()
        return row["content"] if row else None


def list_paths(snapshot_id: int) -> list[str]:
    """보관된 파일 경로. 경로 순으로 정렬한다.

    context 의 '## 파일 목록' 과 다르다 — 그쪽은 MAX_TREE_ENTRIES 로 잘린 트리 조회
    결과이고, 이쪽은 **실제로 보관된 것**이다. 도구가 읽을 수 있는 범위가 곧 이 목록이다.
    """
    with cursor(commit=False) as cur:
        cur.execute(
            "SELECT path FROM snapshot_source_files WHERE snapshot_id = %s"
            " ORDER BY path",
            (snapshot_id,),
        )
        return [row["path"] for row in cur.fetchall()]


def count(snapshot_id: int) -> int:
    """보관된 파일 수. 0 이면 이 스냅샷에는 소스가 없다.

    "왜 없는가"(아직 색인 전인가, 크기 상한을 넘어 포기했는가)는 여기서 답하지 않는다.
    상태 열을 따로 두면 그 값과 실제 행 수가 어긋날 자리가 생긴다 — 사유는 로그에 남는다.
    """
    with cursor(commit=False) as cur:
        cur.execute(
            "SELECT count(*) AS n FROM snapshot_source_files WHERE snapshot_id = %s",
            (snapshot_id,),
        )
        return cur.fetchone()["n"]
