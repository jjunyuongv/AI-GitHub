from datetime import datetime

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    github_url: str
    # 브라우저가 갖고 있는 기존 세션. 같은 스냅샷을 보고 있으면 그대로 이어 쓴다.
    # 이 값이 없으면 서버는 분석마다 새 세션을 만들 수밖에 없다 —
    # "이 사람이 이어갈 대화가 있는가"는 localStorage 에만 있는 정보다.
    session_id: str | None = None


class RepoMeta(BaseModel):
    owner: str
    name: str
    description: str | None
    primary_language: str | None
    stars: int


class AnalyzeResponse(BaseModel):
    repo: RepoMeta
    summary: str
    # 후속 질문에 쓸 대화 세션. DB를 쓸 수 없으면 None이고, 그때는 요약만 볼 수 있다.
    session_id: str | None = None


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    session_id: str
    answer: str


class ChatMessage(BaseModel):
    role: str
    content: str
    created_at: datetime


class ChatRepo(BaseModel):
    """대화 이력에 붙는 저장소 표기.

    설명·별점은 GitHub 을 호출해야 알 수 있어서 넣지 않는다 (이 조회는 외부 호출 0회다).
    """

    owner: str
    name: str


class ChatHistory(BaseModel):
    session_id: str
    repo: ChatRepo
    summary: str
    messages: list[ChatMessage]


class IndexStatus(BaseModel):
    """코드 색인 진행 상황.

    status 가 completed 가 되기 전에는 답변에 코드가 쓰이지 않는다 —
    화면은 그 사이 진행 상황을, 실패하면 사유(error)를 보여준다.
    """

    status: str  # pending | running | completed | failed
    chunks_total: int = 0
    chunks_done: int = 0
    # 남은 예상 시간(초). 진행이 없어 계산할 수 없으면 None.
    eta_seconds: int | None = None
    error: str | None = None


class RunRequest(BaseModel):
    github_url: str
    model: str
    effort: str
    system_prompt: str | None = None


class ResummarizeRequest(BaseModel):
    """요약만 강제로 다시 만든다 (LLM 호출·과금). model/effort를 비우면 서비스 기본값.

    청크 재생성은 RebuildRequest 다 — 무과금이고 비동기라 요청 형태가 다르다.
    """

    github_url: str
    model: str | None = None
    effort: str | None = None


class RebuildRequest(BaseModel):
    """코드 색인만 다시 만든다 (LLM 없음).

    **저장소 URL 이 아니라 snapshot_id 를 받는다.** 세션이 보는 코드 버전은 스냅샷으로
    확정돼 있어서, URL 로 받으면 어느 스냅샷을 다시 만드는지가 모호해진다.
    table 을 비우면 지금 쓰는 청크 테이블을 쓴다.
    """

    snapshot_id: int
    table: str | None = None


class RollbackRequest(BaseModel):
    """검색이 보는 빌드를 지정한 빌드로 되돌린다."""

    snapshot_id: int
    build_id: int
    table: str | None = None


class RunResult(BaseModel):
    ts: str
    source: str
    cached: bool = False  # 옛 기록에는 없는 필드
    repo: str
    model: str
    effort: str | None
    fetch_ms: int
    llm_ms: int
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int = 0  # 옛 기록에는 없는 필드
    cache_read_tokens: int
    cost_usd: float | None
    context_chars: int
    system_prompt: str
    summary: str
