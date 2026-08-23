import logging
import time
import uuid
from collections import Counter
from datetime import datetime, timezone

import anthropic
from fastapi import APIRouter, HTTPException, Request

from app.db import chats, index_status
from app.db import sources as source_store
from app.db.pool import DB_ERRORS
from app.schemas.schemas import (
    ChatHistory,
    ChatRequest,
    ChatResponse,
    FileView,
    IndexStatus,
)
from app.services import citations, indexer, rate_limit, run_log, tools
from app.services.context_builder import number_lines
from app.services.claude_client import (
    CHAT_SYSTEM_PROMPT,
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    MAX_HISTORY_MESSAGES,
    MODELS,
    MissingAPIKeyError,
    billable_tokens,
    run_chat,
)

router = APIRouter()

logger = logging.getLogger(__name__)

DB_UNAVAILABLE = "대화 기능을 쓸 수 없습니다 (데이터베이스 연결 실패). 잠시 후 다시 시도해 주세요."
SESSION_NOT_FOUND = "대화를 찾을 수 없습니다. 저장소를 다시 분석해 주세요."

# 인용이 가리킨 범위 앞뒤로 함께 보여줄 줄 수.
#
# **행 번호가 27.6% 확률로 틀린다**(실측 118/163). 딱 그 범위만 보여주면 틀렸을 때
# 막다른 길이 된다 — 사용자가 "여기 없는데?" 에서 멈춘다. 실제로 관측된 어긋남이
# +3 ~ +22 행이었으므로(`context_builder.number_lines` 주석), 그만큼 어긋나도 같은
# 화면에 들어오게 20 을 잡는다.
CITATION_CONTEXT_LINES = 20

# 한 번에 돌려줄 줄 수 상한. `tools.MAX_TOOL_RESULT_TOKENS` 와 같은 성격이지만
# 여기는 사람이 읽으므로 토큰이 아니라 줄로 자른다.
MAX_FILE_VIEW_LINES = 400


def _stored_paths(snapshot_id: int) -> list[str]:
    """인용 경로를 해석할 목록. 읽지 못하면 빈 목록.

    **실패를 삼킨다.** 인용은 답변에 링크를 더하는 부가 기능이라, 이것 때문에 답변이나
    이력이 막히면 안 된다 — 링크가 없는 화면이 503 보다 낫다.

    경로 해석이 이 목록에 기대므로 **보관 소스가 없으면 저절로 빈 목록이 된다.**
    죽은 링크를 만들어 놓고 404 를 띄우는 경우가 구조적으로 생기지 않는다.
    """
    try:
        return source_store.list_paths(snapshot_id)
    except DB_ERRORS as e:
        logger.warning("보관 경로를 읽지 못해 인용을 만들지 않습니다 (%s): %s", snapshot_id, e)
        return []


def _load_session(session_id: str) -> dict:
    """세션을 읽는다. 없으면 404, DB를 못 쓰면 503.

    /analyze 와 달리 대화는 DB 없이 대신할 방법이 없다. 조용히 넘어가지 않고 503을 낸다.
    """
    # UUID 가 아닌 값을 그대로 넘기면 DB 가 형식 오류를 내고 503으로 뭉개진다.
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="대화 id 형식이 올바르지 않습니다.")

    try:
        session = chats.get_session(session_id)
    except DB_ERRORS:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE)
    if not session:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
    return session


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request):
    question = req.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="질문이 비어 있습니다.")

    session = _load_session(req.session_id)

    # 질문 하나가 LLM 호출 하나다. /analyze 캐시 미스와 같은 무게로 센다.
    try:
        rate_limit.check_and_reserve(rate_limit.client_ip(request))
    except rate_limit.RateLimitExceeded as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=str(e),
            headers={"Retry-After": str(e.retry_after)},
        )

    started = time.perf_counter()
    try:
        history = chats.list_messages(req.session_id, limit=MAX_HISTORY_MESSAGES)
    except DB_ERRORS:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE)

    # **검색을 미리 돌리지 않는다.** 예전에는 질문마다 한 번 검색해 그 결과를 마지막
    # 사용자 메시지에 넣었는데, 그 자리는 캐시 브레이크포인트 뒤라 도구 루프가 생기면
    # 라운드트립마다 정가로 되풀이 청구된다 (실측 산식으로 3회에 3.78배, 판정 기준 C 초과).
    # 이제 모델이 필요할 때 search_code 를 부른다.
    #
    # 전체 주입 스냅샷(작은 저장소)은 소스가 이미 접두사에 다 들어가 있으므로 도구를
    # 붙이지 않는다 — 부를 이유가 없고, 도구 목록이 갈리는 문제도 여기서는 생기지 않는다.
    # 두 경로는 스냅샷 속성으로 갈리고 한 대화 안에서는 바뀌지 않는다.
    #
    # 인덱싱이 **끝났을 때만** 도구를 준다. 진행 중인 인덱스로 검색하면 아직 임베딩하지
    # 않은 코드가 '저장소에 없는 코드'처럼 보여 틀린 답을 만든다. 아직이면 요약만으로
    # 답하고, 화면은 GET /chat/{id}/index 로 진행 상황을 보여준다.
    source_bundle = session.get("source_bundle") or ""
    tool_schemas, execute = None, None
    try:
        if not source_bundle:
            if indexer.is_ready(session["snapshot_id"]):
                # 보관 소스가 없는 스냅샷은 read_file·grep 이 빈손이라 목록에서 빠진다
                # (services/tools.build 참고 — 캐시 접두사가 왜 안 깨지는지도 거기 있다).
                tool_schemas, execute = tools.build(session["snapshot_id"])
            else:
                # 세션만 복원해 들어온 경우(/analyze 를 거치지 않음) 여기서 시작시킨다.
                indexer.start(session["snapshot_id"], session["owner"], session["name"])
    except Exception as e:
        # 실패해도 진행한다 — 코드 근거 없이 답하는 쪽이 질문을 막는 것보다 낫다.
        logger.warning("도구를 붙이지 못했습니다 (%s): %s", req.session_id, e)
        tool_schemas, execute = None, None
    fetch_ms = int((time.perf_counter() - started) * 1000)

    try:
        result = run_chat(
            context=session["context"],
            summary=session["summary"],
            history=history,
            question=question,
            source_bundle=source_bundle,
            tools=tool_schemas,
            execute=execute,
        )
    except MissingAPIKeyError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Claude API 오류: {e}")

    # 질문과 답변은 LLM 호출이 성공한 뒤에 함께 저장한다. 미리 넣으면 호출이 실패했을 때
    # 질문만 남아 다음 요청의 이력이 어긋난다 (chats.add_exchange 주석 참고).
    try:
        chats.add_exchange(req.session_id, question, result["text"])
    except DB_ERRORS as e:
        # 토큰은 이미 썼다. 답변은 돌려주고 기록만 포기한다.
        logger.warning("대화를 저장하지 못했습니다 (%s): %s", req.session_id, e)

    run_log.append_run(
        source="chat",
        repo=f"{session['display_owner'].lower()}/{session['display_name'].lower()}",
        model=DEFAULT_MODEL,
        effort=DEFAULT_EFFORT if MODELS[DEFAULT_MODEL]["effort"] else None,
        fetch_ms=fetch_ms,
        context=session["context"],
        system_prompt=CHAT_SYSTEM_PROMPT,
        result=result,
    )
    rate_limit.record_tokens(billable_tokens(result))

    # **유실을 센다.** 행 표기를 잡고도 인용을 못 만든 건수다 — 화면의 `onMiss` 는
    # 인용을 받은 뒤 링크를 못 건 것만 세므로 이쪽 유실은 어디에도 안 잡혔다.
    dropped: Counter = Counter()
    cites = citations.for_answer(
        result["text"], _stored_paths(session["snapshot_id"]), dropped
    )
    if dropped:
        logger.info(
            "인용 %d건 · 행 표기를 잡고도 버림 %d건 (%s)",
            len(cites),
            sum(dropped.values()),
            ", ".join(f"{reason} {n}" for reason, n in dropped.most_common()),
        )

    return ChatResponse(
        session_id=req.session_id,
        answer=result["text"],
        citations=cites,
    )


@router.get("/chat/{session_id}/file", response_model=FileView)
def file_view(session_id: str, path: str, start: int, end: int):
    """인용이 가리킨 파일 조각. 앞뒤 여유를 붙여 돌려준다.

    **세션의 스냅샷에 묶인다.** `path` 는 그 스냅샷에 보관된 것만 읽는다 — 임의 경로를
    받지 않는다. DB 키 조회라 파일시스템에 애초에 닿지 않으므로 `..` 같은 경로 조작이
    성립하지 않는다.

    도구의 `read_file` 과 **같은 형식**(`12|코드`)으로 준다. 형식이 갈리면 화면과 모델이
    다른 것을 보게 된다. GitHub·LLM 호출이 없어 남용 제한도 걸지 않는다.
    """
    session = _load_session(session_id)
    try:
        content = source_store.get_file(session["snapshot_id"], path)
    except DB_ERRORS:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE)
    if content is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{path}' 는 이 대화가 보는 스냅샷에 보관돼 있지 않습니다.",
        )

    lines = content.splitlines()
    # **요청 범위를 그대로 되돌려 준다.** 파일 밖을 가리켜도 고쳐 주지 않는다 —
    # 화면이 "인용이 여기라고 했다"를 보여줘야 틀린 것이 눈에 띈다.
    first = max(1, start - CITATION_CONTEXT_LINES)
    last = min(len(lines), end + CITATION_CONTEXT_LINES)
    truncated = last - first + 1 > MAX_FILE_VIEW_LINES
    if truncated:
        last = first + MAX_FILE_VIEW_LINES - 1

    chunk = "\n".join(lines[first - 1 : last]) if first <= len(lines) else ""
    return FileView(
        path=path,
        start_line=first,
        end_line=last,
        requested_start=start,
        requested_end=end,
        total_lines=len(lines),
        truncated=truncated,
        numbered=number_lines(chunk, first) if chunk else "",
    )


@router.get("/chat/{session_id}/index", response_model=IndexStatus)
def index_status_view(session_id: str):
    """코드 색인 진행 상황. 외부 호출이 없어 남용 제한도 걸지 않는다.

    상태 행이 아직 없으면 pending 으로 답한다 — /analyze 가 인덱싱을 시작하기
    직전이거나, DB 에 기록되기 전 찰나에 화면이 물어본 경우다.
    """
    session = _load_session(session_id)
    try:
        row = index_status.get(session["snapshot_id"])
    except DB_ERRORS:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE)

    if not row:
        return IndexStatus(status=index_status.PENDING)

    return IndexStatus(
        status=row["status"],
        chunks_total=row["chunks_total"],
        chunks_done=row["chunks_done"],
        eta_seconds=_eta_seconds(row),
        error=row["error"],
    )


def _eta_seconds(row: dict) -> int | None:
    """남은 예상 시간. 지금까지의 실제 속도로 계산한다.

    청크당 시간은 저장소·기기마다 다르고(같은 모델도 청크 길이에 좌우된다),
    고정값을 박으면 늘 틀린다. 진행이 없으면(0개) 계산할 수 없어 None.

    기준 시각(started_at)은 임베딩이 시작된 시점이다 — set_total() 이 그때 다시 찍는다.
    """
    if row["status"] != index_status.RUNNING:
        return None
    done, total, started_at = row["chunks_done"], row["chunks_total"], row["started_at"]
    if not done or not total or not started_at or done >= total:
        return None
    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    return max(0, round(elapsed / done * (total - done)))


@router.get("/chat/{session_id}", response_model=ChatHistory)
def history(session_id: str):
    """대화 이력. GitHub·LLM 호출이 없어 남용 제한도 걸지 않는다."""
    session = _load_session(session_id)
    try:
        messages = chats.list_messages(session_id)
    except DB_ERRORS:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE)

    # **이력에도 인용을 붙인다.** 안 붙이면 새로고침했을 때 링크가 사라진다.
    # 추출은 순수 정규식이라 무과금이고, 보관 경로는 한 번만 읽는다.
    paths = _stored_paths(session["snapshot_id"])

    return ChatHistory(
        session_id=session_id,
        repo={"owner": session["display_owner"], "name": session["display_name"]},
        summary=session["summary"],
        messages=[
            {
                **m,
                "citations": (
                    citations.for_answer(m["content"], paths)
                    if m["role"] == "assistant"
                    else []
                ),
            }
            for m in messages
        ],
    )
