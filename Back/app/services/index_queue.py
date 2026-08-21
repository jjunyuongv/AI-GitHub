"""색인 재생성 큐 — 워커 하나가 순서대로 처리한다.

**왜 큐인가.** 인덱싱은 CPU 를 다 쓰는 작업이라(임베딩) 둘을 동시에 돌리면 둘 다
느려진다. 큰 저장소 하나가 40~96분인데 서너 개가 겹치면 어느 것도 끝나지 않는다.

**왜 자동으로 넣지 않는가.** 규칙이 바뀌면 모든 저장소의 색인이 한꺼번에 낡는다.
그때 자동으로 큐에 넣으면 배포 직후 전 저장소가 재색인에 들어가고, 그동안 서버는
임베딩에 CPU 를 다 쓴다. 무엇을 언제 다시 만들지는 사람이 정한다.

**단일 프로세스 전제다.** 큐가 메모리에 있어서 `uvicorn --workers 2` 이상이면
워커마다 다른 큐를 갖는다 (rate_limit·reset_running 과 같은 전제).
"""

import logging
import queue
import threading

from app.db.pool import DB_ERRORS
from app.services import indexer

logger = logging.getLogger(__name__)

_queue: "queue.Queue[tuple]" = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def _ensure_worker() -> None:
    """워커 스레드를 (없으면) 띄운다. 첫 요청 때 시작한다 — 쓰지 않는 서버가
    스레드를 들고 있을 이유가 없다."""
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="index-queue", daemon=True)
            _worker.start()


def _run() -> None:
    while True:
        snapshot_id, owner, repo, ref, table, build_id, files = _queue.get()
        try:
            indexer.run_build(build_id, snapshot_id, owner, repo, ref, table, files)
        except Exception as e:
            # 워커가 죽으면 이후 요청이 영영 처리되지 않는다. 어떤 실패든 삼킨다.
            logger.warning("색인 빌드 #%s 처리 중 오류: %s", build_id, e)
        finally:
            # **넘겨받은 소스는 여기서 놓는다.** 큐 항목이 참조를 들고 있으면
            # 처리가 끝난 뒤에도 다음 항목이 올 때까지 메모리에 남는다.
            files = None
            _queue.task_done()


def submit(
    snapshot_id: int,
    owner: str,
    repo: str,
    ref: str = "",
    table: str | None = None,
    files: dict[str, str] | None = None,
) -> int | None:
    """색인 재생성을 큐에 넣는다. 넣었으면 build_id, 이미 진행 중이면 None.

    중복 판정은 DB 가 한다(같은 대상에 pending/running 빌드가 있으면 begin() 이 None).
    큐를 보고 판정하면 이미 꺼내 처리 중인 작업을 놓친다.

    `files` 는 호출부가 방금 받아 둔 소스다. 주면 워커가 tarball 을 다시 받지 않는다.
    **크기 판정은 호출부(`indexer.start`)가 이미 했다** — 여기서 다시 재지 않는다.
    """
    from app.core.chunk_rule import rule_version
    from app.db import index_status

    try:
        build_id = index_status.begin(snapshot_id, table=table, chunk_rule=rule_version())
    except DB_ERRORS as e:
        logger.warning("색인 빌드를 시작하지 못했습니다 (스냅샷 %s): %s", snapshot_id, e)
        return None
    if build_id is None:
        return None

    _ensure_worker()
    _queue.put((snapshot_id, owner, repo, ref, table, build_id, files))
    return build_id


def pending_count() -> int:
    """큐에서 차례를 기다리는 작업 수 (처리 중인 것은 빼고)."""
    return _queue.qsize()
