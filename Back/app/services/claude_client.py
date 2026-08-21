import logging
import time
from datetime import date

import anthropic

from app.config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_EFFORT = "medium"

# effort를 지원하지 않는 모델에 output_config를 보내면 API가 거부한다.
MODELS = {
    "claude-sonnet-5": {"effort": True},
    "claude-haiku-4-5": {"effort": False},
}

EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]

MAX_TOKENS = 4096

# 후속 질문에 함께 보낼 지난 메시지 수. 오래된 턴부터 버린다.
# 자르는 지점은 cache_control 을 건 스냅샷 블록보다 뒤라서 캐시 접두사는 깨지지 않는다.
MAX_HISTORY_MESSAGES = 20

# 1M 토큰당 USD (input, output).
PRICING = {
    "claude-haiku-4-5": (1.00, 5.00),
}

# sonnet-5 는 도입가 기간이 있다. 마지막 날까지 $2/$10, 다음 날부터 정가 $3/$15.
#
# **날짜로 가른다.** 전에는 "그때 수정할 것"이라는 주석만 두었는데, 그 방식은 사람이
# 잊으면 그날부터 조용히 33% 적은 비용을 쌓는다 — 틀렸다는 신호가 어디에도 안 뜬다.
# (청킹 규칙 해시를 손으로 올리지 않게 만든 것과 같은 이유다)
SONNET_5_INTRO_LAST_DAY = date(2026, 8, 31)
SONNET_5_INTRO_PRICE = (2.00, 10.00)
SONNET_5_LIST_PRICE = (3.00, 15.00)

# 캐시 토큰의 입력 단가 배율. 읽기는 정가의 0.1배, 쓰기는 기본 TTL(5분)이 1.25배다.
# ttl="1h" 로 바꾸면 쓰기가 2.0배가 되므로 그때 이 값도 함께 고쳐야 한다.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def pricing_for(model: str, at: date | None = None) -> tuple[float, float] | None:
    """그 시점의 1M 토큰당 단가. 모르는 모델이면 None.

    at 을 주면 그 날짜 기준으로 고른다 — 옛 기록을 다시 계산할 때 쓴다.
    """
    if model == "claude-sonnet-5":
        day = at or date.today()
        return (
            SONNET_5_INTRO_PRICE if day <= SONNET_5_INTRO_LAST_DAY else SONNET_5_LIST_PRICE
        )
    return PRICING.get(model)


class MissingAPIKeyError(Exception):
    pass

SYSTEM_PROMPT = """당신은 GitHub 레포지토리를 분석해 개발자에게 설명하는 어시스턴트입니다.
주어진 레포지토리 정보(README, 매니페스트 파일, 파일 목록, 그리고 있을 경우 정적분석 결과)를
읽고 아래 형식에 맞춰 한국어 마크다운으로 정리하세요.

<length_constraints>
- 전체 응답은 400~600단어를 넘지 않게 작성하세요.
- 각 항목은 "라이브러리명 + 한 줄 용도"로만 적으세요.
  왜 그 라이브러리가 쓰였는지, 주석 처리 여부 같은 세부 추론 과정은
  생략하고 결론만 반영하세요.
- 확실하지 않은 항목은 아예 나열에서 제외하거나 문장 끝에 "(추정)"만
  붙이고, 별도 설명 문장을 추가하지 마세요.
- 목록 항목은 최대 5~7개로 제한하고, 부차적인 것은 "기타: A, B, C"
  형태로 한 줄에 묶으세요.
- "정보 부족"이라고 쓸 항목은 언급하되 이유를 설명하지 말고
  한 문장으로 끝내세요.
</length_constraints>

<output_format>
## 프로젝트 개요
2~3문장.

## 기술 스택 (핵심만)
- 백엔드: 언어/프레임워크 + 핵심 AI 라이브러리 3~5개 (한 줄씩)
- 프론트: 언어/프레임워크 + 핵심 라이브러리 3~5개 (한 줄씩)

## 프로젝트 구조 (핵심 디렉터리만)
핵심 디렉터리 5~7개만 골라 아래처럼 코드블록 안에 트리로 그리세요.
표(table)는 절대 쓰지 마세요. 설명은 5단어 이내로 뒤에 붙이고,
경로는 최상위부터 쓰지 말고 디렉터리 이름만 쓰세요.

```
repo/
├─ back/
│  ├─ routers/    API 엔드포인트 라우팅
│  └─ services/   비즈니스 로직
└─ front/
   └─ src/        화면 컴포넌트
```

## 코드 상태
**"## 정적분석" 블록이 주어졌을 때만** 이 항목을 쓰세요. 없으면 항목째 생략합니다
(린터를 안 돌린 것이지 코드가 깨끗한 것이 아닙니다 — 없는데 "문제 없음"이라고 쓰면 거짓입니다).

- 검사 범위를 먼저 한 줄로 밝히세요: 어떤 언어 몇 개 파일인지.
- 눈에 띄는 것 2~3개만 한 줄씩. **버그로 이어지는 것을 앞에 두세요**
  (정의되지 않은 이름 > 미사용 변수 > 미사용 import 순).
- 경고가 몰린 파일이 있으면 한 줄로 언급하세요.
- 주어진 집계에 없는 수치를 지어내지 마세요.
</output_format>"""

CHAT_SYSTEM_PROMPT = """당신은 GitHub 레포지토리에 대한 질문에 답하는 어시스턴트입니다.
첫 번째 사용자 메시지는 그 레포지토리의 원본 정보(README, 매니페스트 파일, 파일 목록)이고,
이어지는 어시스턴트 메시지는 앞서 만든 요약입니다. 그 뒤부터가 실제 대화입니다.

코드는 저장소 크기에 따라 둘 중 한 형태로 옵니다. 둘 다 **실제 소스 코드**입니다.
- 첫 번째 사용자 메시지의 "## 저장소 전체 소스" — 작은 저장소라 전부 들어왔습니다.
  각 줄 앞에 줄 번호가 `12|코드` 로 붙어 있습니다.
- 마지막 사용자 메시지의 "## 질문과 관련된 코드" — 큰 저장소라 질문과 가까운 순으로 검색된 일부입니다.
  **각 줄에는 번호가 없고**, 조각 머리글에 `(42-58행)` 처럼 그 조각이 원본에서 차지하는
  범위만 적혀 있습니다.

<rules>
- 한국어 마크다운으로 답하세요.
- 주어진 정보에서 확인되는 내용만 답하세요. 근거가 없으면 "주어진 정보로는 알 수 없습니다"라고
  한 문장으로 밝히고, 추측으로 채우지 마세요. 추론이 필요하면 문장 끝에 "(추정)"을 붙이세요.
- 코드가 함께 왔다면 그 코드를 근거로 답하고, 어느 파일 몇 행인지 밝히세요.
  코드에서 확인한 사실에는 "(추정)"을 붙이지 마세요.
- **행 번호는 주어진 것만 쓰세요.**
  줄 번호가 붙어 온 코드(`12|코드`)는 그 숫자를 그대로 읽고, 직접 세지 마세요.
  머리글에 범위만 있는 조각은 **그 범위를 그대로 인용하세요**(예: "42-58행의 `login()`").
  조각 안에서 특정 줄을 세어 짚지 마세요 — 조각은 원본과 줄이 정확히 맞지 않습니다.
  확실하지 않으면 행 번호 없이 함수·클래스 이름으로만 위치를 알려주세요.
  **틀린 행 번호는 없는 것보다 나쁩니다.**
- **검색된** 코드는 저장소의 일부일 뿐입니다. 관련 코드가 오지 않았다면 "검색된 범위에는 없습니다"라고
  밝히되, 파일 목록에서 짐작되는 위치는 알려주세요.
  전체 소스가 온 경우에는 그 말을 쓰지 마세요 — 없으면 저장소에 없는 것입니다.
- 3~5문장 또는 목록 5개 이내로 답하세요. 질문이 넓으면 핵심만 답하고 되묻지 마세요.
- 요약을 반복하지 말고 질문에만 답하세요.
</rules>"""


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    at: date | None = None,
    *,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float | None:
    """실제 청구액 추정. 캐시로 처리된 토큰도 함께 센다.

    **usage.input_tokens 는 캐시에 걸리지 않은 나머지만 센 값이다.** 캐시로 처리된
    토큰은 거기 없고 따로, 다른 배율로 청구된다. 셋을 다 넣지 않으면 캐시를 쓸수록
    비용이 적어 보이는 착시가 생긴다 — 실측(6턴 대화 세션)에서 32% 가 빠져 있었다.
    """
    price = pricing_for(model, at)
    if not price:
        return None
    billed_input = (
        input_tokens
        + cache_write_tokens * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * CACHE_READ_MULTIPLIER
    )
    return (billed_input * price[0] + output_tokens * price[1]) / 1_000_000


def count_input_tokens(text: str, model: str = DEFAULT_MODEL) -> int | None:
    """이 텍스트가 프롬프트에서 차지할 토큰 수. 셀 수 없으면 None.

    **무과금이다** — 토큰 계산 엔드포인트는 추론을 돌리지 않는다. 그래서 우회 판정에
    쓸 수 있다(이 프로젝트는 검증에 과금 경로를 쓰지 않는다).

    이름이 `core.embeddings.count_tokens` 와 겹치지 않게 구분해 둔다 — 그쪽은 임베딩
    모델(e5/jina)의 토크나이저이고 여기는 Claude 것이다. 둘의 수는 서로 다르다.

    실패를 삼키고 None 을 돌려준다. 호출부가 문자 수 추정으로 내려갈 수 있어야 하는데,
    여기서 예외를 올리면 토큰을 못 세었다는 이유로 인덱싱 전체가 실패한다.
    """
    if not text or not ANTHROPIC_API_KEY:
        return None
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        return client.messages.count_tokens(
            model=model, messages=[{"role": "user", "content": text}]
        ).input_tokens
    except (anthropic.APIError, ValueError) as e:
        logger.warning("토큰 수를 세지 못했습니다 (%s): %s", model, e)
        return None


def billable_tokens(result: dict) -> int:
    """일일 상한에 셀 토큰 수. _call() 결과를 그대로 받는다.

    캐시 토큰을 빼면 안 된다 — 단가가 다를 뿐 실제로 처리되고 청구되는 토큰이다.
    전체 주입처럼 캐시 접두사가 큰 경로에서는 이 몫이 대부분을 차지하므로,
    빼고 세면 상한이 사실상 꺼진 것과 같아진다.
    """
    return (
        result["input_tokens"]
        + result["output_tokens"]
        + result["cache_write_tokens"]
        + result["cache_read_tokens"]
    )


def _call(*, model: str, effort: str, system: str, messages: list[dict]) -> dict:
    """Claude 를 한 번 호출하고 응답과 함께 소요시간·토큰·비용을 돌려준다."""
    if not ANTHROPIC_API_KEY:
        raise MissingAPIKeyError(
            "ANTHROPIC_API_KEY가 설정되지 않았습니다. Back/.env 에 키를 넣고 서버를 재시작하세요."
        )

    params = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": messages,
    }
    if MODELS.get(model, {}).get("effort"):
        params["output_config"] = {"effort": effort}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    started = time.perf_counter()
    response = client.messages.create(**params)
    llm_ms = int((time.perf_counter() - started) * 1000)

    usage = response.usage
    cache_write = usage.cache_creation_input_tokens or 0
    cache_read = usage.cache_read_input_tokens or 0
    return {
        "text": "".join(block.text for block in response.content if block.type == "text"),
        "llm_ms": llm_ms,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_write_tokens": cache_write,
        "cache_read_tokens": cache_read,
        "cost_usd": estimate_cost(
            model,
            usage.input_tokens,
            usage.output_tokens,
            cache_write_tokens=cache_write,
            cache_read_tokens=cache_read,
        ),
    }


def run_summary(
    context: str,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    system: str = SYSTEM_PROMPT,
) -> dict:
    """요약을 실행하고 응답과 함께 소요시간·토큰·비용을 돌려준다."""
    return _call(
        model=model,
        effort=effort,
        system=system,
        messages=[{"role": "user", "content": context}],
    )


def build_chat_messages(
    context: str,
    summary: str,
    history: list[dict],
    question: str,
    snippets: str = "",
    source_bundle: str = "",
) -> list[dict]:
    """대화용 messages 배열.

    스냅샷 원문을 첫 사용자 메시지로 두고 **거기에 cache_control 을 건다.**
    대화가 길어져도 그 앞부분은 캐시에서 읽힌다. 다만 읽기가 0.1배일 뿐 쓰기가 1.25배라,
    질문 N회 세션의 실효 배율은 `(1.25 + 0.1(N−1))/N` 이다 (실측 0.45배).

    **작은 저장소는 source_bundle 이 온다** — 검색 대신 소스 전체다. 이것도 스냅샷마다
    고정이므로 같은 캐시 접두사에 넣는다. 질문마다 달라지는 snippets 와 달리
    여기 넣어야 캐시가 산다.

    history 는 오래된 순의 {role, content} 목록이다. user/assistant 가 번갈아 나오는
    형태여야 하며(chats.add_exchange 가 둘을 한 트랜잭션으로 넣어 보장한다),
    최근 MAX_HISTORY_MESSAGES 개만 남긴다.

    **검색된 코드(snippets)는 반드시 마지막 사용자 메시지에 붙인다.** 질문마다 내용이
    달라지므로 캐시 지점(첫 메시지)에 넣으면 매 질문이 캐시를 깨뜨려, 스냅샷 전체를
    정가로 다시 계산하게 된다.
    """
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"{context}\n\n{source_bundle}" if source_bundle else context,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
        {"role": "assistant", "content": summary},
        *(
            {"role": m["role"], "content": m["content"]}
            for m in history[-MAX_HISTORY_MESSAGES:]
        ),
        {
            "role": "user",
            "content": f"{snippets}\n\n---\n\n{question}" if snippets else question,
        },
    ]


def run_chat(
    context: str,
    summary: str,
    history: list[dict],
    question: str,
    snippets: str = "",
    source_bundle: str = "",
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
) -> dict:
    """후속 질문에 답한다. 반환 dict 는 run_summary() 와 같은 키 집합이다
    (run_log.append_run() 을 그대로 재사용한다)."""
    return _call(
        model=model,
        effort=effort,
        system=CHAT_SYSTEM_PROMPT,
        messages=build_chat_messages(
            context, summary, history, question, snippets, source_bundle
        ),
    )
