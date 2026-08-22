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


class Citation(BaseModel):
    """답변이 짚은 근거 한 건. 화면이 이걸로 링크를 건다.

    **행 번호는 검증되지 않은 값이다** — 실측 정확도가 72.4% 다. 서버는 맞았는지
    판정하지 않고 그대로 넘긴다. 틀린 것을 감추면 고칠 수가 없다.

    `offset` 은 답변 문자열 안에서 `marker` 가 시작하는 위치다. 화면은 offset 으로
    렌더 트리의 노드를 고르고 `marker` 로 그 안의 위치를 정한다 — 마크다운 렌더러가
    줄 앞뒤 공백을 지워서 offset 산술만으로는 어긋난다.
    """

    path: str
    start_line: int
    end_line: int
    marker: str
    offset: int


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    # 보관 소스가 없는 스냅샷에서는 빈 목록이다 (경로가 해석되지 않는다).
    citations: list[Citation] = []


class ChatMessage(BaseModel):
    role: str
    content: str
    created_at: datetime
    # 사용자 메시지에는 없다. 이력을 복원했을 때도 링크가 살아 있어야 해서 여기 싣는다.
    citations: list[Citation] = []


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


class FileView(BaseModel):
    """인용이 가리킨 파일의 한 조각.

    **요청 범위와 실제 반환 범위를 둘 다 준다.** 화면이 "인용이 가리킨 줄"을
    하이라이트하고 앞뒤 여유와 구분하려면 둘이 다 필요하다.
    """

    path: str
    # 실제로 담긴 범위 (앞뒤 여유가 붙어 있다)
    start_line: int
    end_line: int
    # 인용이 요청한 범위. 파일 밖을 가리켰으면 그대로 돌려준다 — 틀린 것을 감추지 않는다.
    requested_start: int
    requested_end: int
    total_lines: int
    truncated: bool
    # `12|코드` 형식. 도구의 read_file 과 같은 형식이다.
    numbered: str


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
