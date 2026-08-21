import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, analyze, chat, health
from app.config import FRONTEND_ORIGIN
from app.core import embeddings
from app.core.chunk_rule import rule_version
from app.db import index_status, pool

logger = logging.getLogger(__name__)


def _log_stale_indexes() -> None:
    """옛 청킹 규칙으로 만들어진 인덱스를 기동할 때 알린다.

    **자동으로 다시 만들지 않는다.** 큰 저장소는 임베딩만 수십 분이고, 서버를 올릴
    때마다 그게 시작되면 기동이 곧 장애가 된다. 무엇이 낡았는지만 알리고 재색인
    시점은 사람이 정한다.
    """
    try:
        current = rule_version()
        stale = index_status.stale(current)
    except pool.DB_ERRORS as e:
        logger.warning("청킹 규칙을 점검하지 못했습니다: %s", e)
        return
    except Exception as e:
        # 규칙 해시는 부가 정보다. 계산에 실패해도 서버는 떠야 한다.
        logger.warning("청킹 규칙 해시를 계산하지 못했습니다: %s", e)
        return

    if not stale:
        logger.info("청킹 규칙 %s — 낡은 색인 없음", current)
        return

    logger.warning("청킹 규칙이 바뀌어 색인 %d건이 낡았습니다 (현재 %s):", len(stale), current)
    for row in stale:
        logger.warning(
            "  스냅샷 #%s %s/%s [%s]: rule %s ≠ 현재 %s (재색인 필요, 청크 %d개)",
            row["snapshot_id"], row["display_owner"], row["display_name"],
            row["table_name"], row["chunk_rule"], current, row["chunks_actual"],
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 실패해도 앱은 뜬다. DB 없이도 /health 와 (캐시 없는) /analyze 는 동작해야 한다.
    if pool.init_schema():
        # 인덱싱 스레드는 프로세스와 함께 사라진다. 서버가 내려갈 때 진행 중이던
        # 색인은 running 인 채 남아 재시도를 영원히 막으므로 여기서 되돌린다.
        try:
            reset = index_status.reset_running()
            if reset:
                logger.info("중단된 색인 %d건을 다시 대기 상태로 되돌렸습니다.", reset)
        except pool.DB_ERRORS as e:
            logger.warning("중단된 색인을 정리하지 못했습니다: %s", e)

        _log_stale_indexes()

    # 임베딩 모델을 미리 올린다. 첫 호출에서 올리면 그 사용자가 로딩 시간(수십 초)을
    # 고스란히 기다린다. 별도 스레드로 돌려 서버 기동 자체는 막지 않는다 —
    # 모델이 준비되기 전에 질문이 들어오면 그 요청이 로딩을 기다릴 뿐이다.
    threading.Thread(target=embeddings.warm_up, daemon=True).start()

    yield
    pool.close()


app = FastAPI(title="RepoDive API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(analyze.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(admin.root_router)
