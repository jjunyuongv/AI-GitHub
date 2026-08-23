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

# 질문 하나에서 도구를 부를 수 있는 횟수. 넘으면 지금까지 얻은 것으로 답하게 한다.
#
# **비용 상한이다.** 라운드트립 R 회의 입력은 Σₖ(0.1·P + q + Σᵢ<ₖ(aᵢ + rᵢ)) 라
# 꼬리가 이차로 누적된다. 실측 기준선($0.008155/질문)에 P=1,140·q≈40·a_tool=150·
# a_final=330·r=800(tools.MAX_TOOL_RESULT_TOKENS)을 대입하면
#
#     R=3 (호출 4회)  $0.020432  →  2.51배   ✓
#     R=4 (호출 5회)  $0.029840  →  3.66배   ✗ (COST_RATIO_LIMIT 3.0 초과)
#
# 3 이 상한 아래에 남는 마지막 값이다. 남는 0.49배는 effort 가 만드는 사고 토큰
# (출력으로 청구된다)이 a_tool 추정을 넘길 여지를 덮는 몫이다.
MAX_TOOL_ROUND_TRIPS = 3

# 한도에 닿았을 때 꼬리에 덧붙이는 말.
#
# **tool_choice 를 "none" 으로 바꾸지 않는다.** tool_choice 변경은 tools·system 캐시는
# 살리지만 **messages 캐시를 무효화**해서, 마지막 호출이 스냅샷 접두사를 통째로 정가로
# 다시 계산한다. 꼬리에 문장을 더하는 것은 접두사를 건드리지 않는다.
ROUND_TRIP_CAP_NOTICE = (
    "도구 호출 한도에 도달했습니다. 더 부르지 말고 지금까지 얻은 근거로 답하세요."
    " 근거가 모자라면 무엇이 부족한지 밝히세요."
)

# 한도까지 쓰고도 모델이 답을 안 내놓은 경우. 빈 문자열을 돌려주면 화면이 빈 말풍선을
# 띄우고 그 상태가 왜인지 아무 데도 안 남는다.
NO_ANSWER_AFTER_TOOLS = (
    "도구를 여러 번 불렀지만 답을 정리하지 못했습니다. 질문을 좁혀 다시 물어봐 주세요."
)

# 도구를 부르지 않았는데도 텍스트 블록이 하나도 안 온 경우. **실측으로 있었다** —
# 출력 15~16토큰 · 1.5초 · text 블록 0개로 두 번 연속. 남은 것은 thinking 블록뿐이었다
# (`thinking` 을 안 보내도 sonnet-5 는 adaptive 로 돌고, display 기본값이 "omitted" 라
# 그 블록의 text 가 빈 문자열이다. `_text_of` 는 type == "text" 만 join 한다).
#
# **NO_ANSWER_AFTER_TOOLS 를 재사용하지 않는다.** 이 경로는 도구를 쓰지 않았으므로
# 그 문구가 거짓이 된다. 도구 유무와 무관한 말로 따로 둔다.
NO_ANSWER = "답변을 만들지 못했습니다. 질문을 조금 바꿔 다시 물어봐 주세요."

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


# 근거가 없을 때 쓰라고 CHAT_SYSTEM_PROMPT 가 못 박은 문구. 평가 하네스가 "규정대로
# 거절했는가"를 이 문자열로 판정한다 — 인용 정확도와 같은 방식이라 LLM 심판이 필요 없다.
#
# **프롬프트에 f-string 으로 끼워 넣지 않는다.** 끼워 넣으면 정합성이 자동으로 맞아
# 보이지만, 그 순간 `test_refusal_phrases_are_in_the_chat_prompt` 가 동어반복이 되어
# 항상 통과한다 — 문구가 갈라져 하네스가 조용히 0점을 매기는 상황을 못 잡는다.
# 리터럴로 두고 **포함 여부를 검사**하는 쪽이 실제로 깨진다.
NO_BASIS_PHRASE = "주어진 정보로는 알 수 없습니다"
NOT_IN_SEARCH_PHRASE = "검색된 범위에는 없습니다"
REFUSAL_PHRASES = (NO_BASIS_PHRASE, NOT_IN_SEARCH_PHRASE)

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

코드는 아래 경로로 옵니다. 전부 **실제 소스 코드**입니다.
- 첫 번째 사용자 메시지의 "## 저장소 전체 소스" — 작은 저장소라 전부 들어왔습니다.
  각 줄 앞에 줄 번호가 `12|코드` 로 붙어 있습니다.
- 도구를 쓸 수 있다면 **필요할 때 직접 부르세요.** 코드가 미리 들어와 있지 않습니다.
  - `search_code` — 어디를 봐야 할지 모를 때 먼저 씁니다. 결과는 "## 질문과 관련된 코드"
    형식이고, **각 줄에는 번호가 없으며** 조각 머리글에 `(42-58행)` 처럼 그 조각이
    원본에서 차지하는 범위만 적혀 있습니다.
  - `read_file` — 위치를 알아낸 뒤 그 부분을 원문으로 읽습니다. **원본에서 직접 잘라
    오므로 각 줄의 `12|코드` 번호가 정확합니다.** 전체 소스와 같은 형식입니다.
  - `grep` — 식별자가 어디에 정의·사용되는지 찾습니다.
  근거가 모자라면 도구를 한 번 더 부르세요. 다만 같은 것을 되풀이해 찾지는 마세요.

**도구가 볼 수 있는 범위는 색인이 수집한 파일 집합입니다.** 소스가 아닌 확장자(.md 등),
200KB 를 넘는 파일, node_modules 같은 디렉터리는 애초에 수집하지 않습니다.
그러므로 **"저장소에 없다"와 "수집 범위에 없다"는 다른 말입니다** — 찾지 못했을 때는
찾아본 범위를 밝히고, 저장소 자체에 없다고 단정하지 마세요.

<rules>
- 한국어 마크다운으로 답하세요.
- 주어진 정보에서 확인되는 내용만 답하세요. 근거가 없으면 "주어진 정보로는 알 수 없습니다"라고
  한 문장으로 밝히고, 추측으로 채우지 마세요. 추론이 필요하면 문장 끝에 "(추정)"을 붙이세요.
- 코드가 함께 왔다면 그 코드를 근거로 답하고, 어느 파일 몇 행인지 밝히세요.
  코드에서 확인한 사실에는 "(추정)"을 붙이지 마세요.
- **행 번호는 주어진 것만 쓰세요.**
  줄 번호가 붙어 온 코드(`12|코드`)는 그 숫자를 그대로 읽고, 직접 세지 마세요.
  전체 소스와 `read_file` 결과가 여기 해당하며 **그 번호는 정확합니다.**
  **`search_code` 결과만** 머리글에 범위가 있고 본문에 번호가 없습니다. 그 조각은
  **머리글의 범위를 그대로 인용하고**(예: "42-58행의 `login()`") 조각 안에서 특정 줄을
  세어 짚지 마세요 — 검색 조각은 원본과 줄이 정확히 맞지 않습니다.
  정확한 행이 필요하면 `read_file` 로 그 범위를 읽어 번호를 확인하세요.
  확실하지 않으면 행 번호 없이 함수·클래스 이름으로만 위치를 알려주세요.
  **틀린 행 번호는 없는 것보다 나쁩니다.**
- **도구로 찾은** 코드는 저장소의 일부일 뿐입니다. 도구를 써 보고도 관련 코드를 못 찾았다면
  "검색된 범위에는 없습니다"라고 밝히되, 어디를 찾아봤는지와 파일 목록에서 짐작되는 위치는
  알려주세요. **찾아보지도 않고 없다고 하지 마세요.**
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


def _raw_call(
    *, model: str, effort: str, system: str, messages: list[dict], tools=None
) -> tuple:
    """Claude 를 한 번 호출한다. `(응답, 소요시간·토큰·비용)`.

    응답 객체를 함께 돌려주는 이유는 도구 루프 때문이다 — 그쪽은 텍스트가 아니라
    `stop_reason` 과 `content` 블록(특히 tool_use id)을 봐야 한다.

    **`tools` 는 프롬프트 렌더 위치 0 이다.** 요청마다 같은 목록이어야 캐시 접두사가
    갈리지 않는다. 저장소·상태에 따라 목록을 바꾸지 말 것.
    """
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
    if tools:
        params["tools"] = list(tools)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    started = time.perf_counter()
    response = client.messages.create(**params)
    llm_ms = int((time.perf_counter() - started) * 1000)

    usage = response.usage
    cache_write = usage.cache_creation_input_tokens or 0
    cache_read = usage.cache_read_input_tokens or 0
    return response, {
        "llm_ms": llm_ms,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_write_tokens": cache_write,
        "cache_read_tokens": cache_read,
    }


def _call(*, model: str, effort: str, system: str, messages: list[dict]) -> dict:
    """Claude 를 한 번 호출하고 응답과 함께 소요시간·토큰·비용을 돌려준다.

    도구 없이 한 번에 끝나는 경로다 (요약, 그리고 tool use 를 끈 대화).
    """
    response, result = _raw_call(
        model=model, effort=effort, system=system, messages=messages
    )
    return {
        "text": _text_of(response.content),
        **result,
        "cost_usd": estimate_cost(
            model,
            result["input_tokens"],
            result["output_tokens"],
            cache_write_tokens=result["cache_write_tokens"],
            cache_read_tokens=result["cache_read_tokens"],
        ),
    }


def _text_of(content) -> str:
    return "".join(block.text for block in content if block.type == "text")


def _merge(total: dict, result: dict) -> dict:
    """호출 하나의 결과를 누적본에 더한다.

    **토큰을 전부 더해야 한다.** 한 질문이 호출 여럿이 되면서 상한·기록·비용이 전부
    "질문 하나 = 호출 하나" 전제 위에 있었다. 마지막 호출만 세면 일일 상한
    (rate_limit.record_tokens ← billable_tokens)이 사실상 꺼진다.
    """
    for key in (
        "llm_ms", "input_tokens", "output_tokens",
        "cache_write_tokens", "cache_read_tokens",
    ):
        total[key] += result[key]
    return total


def _call_loop(
    *, model: str, effort: str, system: str, messages: list[dict], tools, execute
) -> dict:
    """도구를 쓰는 대화 한 번. 여러 번 호출하고 **합산한 하나의 결과**를 돌려준다.

    반환 dict 는 `_call()` 과 같은 키 집합에 `round_trips`·`hit_round_trip_cap` 이
    더해진 것이다 — `run_log.append_run()` 과 `billable_tokens()` 가 그대로 재사용된다.

    `execute(name, params) -> str` 는 호출부가 스냅샷에 묶어 넘긴다
    (`services/tools.build_executor`). 여기서 DB·검색을 알 이유가 없다.
    """
    totals = {
        "llm_ms": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_write_tokens": 0, "cache_read_tokens": 0,
    }
    messages = list(messages)
    round_trips, capped, text = 0, False, ""
    # 호출별 사용량. 비용 산식의 aᵢ 가 실제로 얼마인지는 이것으로만 알 수 있다 —
    # 지금 산식은 추정치(150) 위에 서 있고, 합계만 남기면 그 가정을 못 검증한다.
    per_call: list[dict] = []
    trace = getattr(execute, "trace", None)

    while True:
        response, result = _raw_call(
            model=model, effort=effort, system=system, messages=messages, tools=tools
        )
        _merge(totals, result)
        per_call.append({**result, "stop_reason": response.stop_reason})
        text = _text_of(response.content)

        calls = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason != "tool_use" or not calls:
            break
        if round_trips >= MAX_TOOL_ROUND_TRIPS:
            # 한도를 다 쓰고 안내까지 했는데 또 부른다. 여기서 끊는다.
            capped = True
            break

        round_trips += 1
        # 응답 블록을 **그대로** 되돌린다. 텍스트만 뽑아 보내면 tool_use id 가 사라져
        # 다음 요청이 거부된다.
        messages.append({"role": "assistant", "content": response.content})

        # **결과는 한 user 메시지에 모아 보낸다.** 나눠 보내면 모델이 병렬 호출을
        # 그만두게 학습된다. 실패한 도구도 빠뜨리지 않고 is_error 로 돌려준다.
        content: list[dict] = []
        traced_from = len(trace) if trace is not None else 0
        for call in calls:
            try:
                output = execute(call.name, call.input)
                is_error = False
            except Exception as e:  # 실행기가 삼키지 못한 것만 여기 온다
                logger.warning("도구 %s 실행 실패: %s", call.name, e)
                output, is_error = f"도구 실행에 실패했습니다: {e}", True
            content.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": output,
                "is_error": is_error,
            })
        # 실행기가 남긴 이번 라운드의 항목에 라운드 번호를 찍는다. 실행기가 내역을
        # 안 남기면(테스트 대역 등) 조용히 건너뛴다 — 루프가 그것에 기대지 않는다.
        if trace is not None:
            for entry in trace[traced_from:]:
                entry["round"] = round_trips

        if round_trips >= MAX_TOOL_ROUND_TRIPS:
            content.append({"type": "text", "text": ROUND_TRIP_CAP_NOTICE})
            capped = True
        messages.append({"role": "user", "content": content})

    return {
        "text": text or (NO_ANSWER_AFTER_TOOLS if round_trips else NO_ANSWER),
        **totals,
        "cost_usd": estimate_cost(
            model,
            totals["input_tokens"],
            totals["output_tokens"],
            cache_write_tokens=totals["cache_write_tokens"],
            cache_read_tokens=totals["cache_read_tokens"],
        ),
        "round_trips": round_trips,
        "hit_round_trip_cap": capped,
        # 아래 둘은 **측정용**이다. 프로덕션은 round_trips 만 runs 에 남기고 이것들은
        # 버린다 — 답변 원문만으로는 비용 산식의 aᵢ·rᵢ 를 사후에 되살릴 수 없어서,
        # 하네스가 jsonl 에 실어 다음 설계의 입력으로 쓴다.
        "calls": per_call,
        "tool_trace": list(trace) if trace is not None else [],
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
    tools=None,
    execute=None,
) -> dict:
    """후속 질문에 답한다. 반환 dict 는 run_summary() 와 같은 키 집합이다
    (run_log.append_run() 을 그대로 재사용한다).

    `tools`·`execute` 를 주면 도구 루프로 간다 — 반환 dict 에 `round_trips` 가 더 붙는다.
    주지 않으면 예전처럼 한 번에 끝난다.

    **`snippets` 인자는 남겨 둔다.** 프로덕션은 더 이상 넘기지 않지만(도구가 대신한다),
    답변 품질 하네스의 기준선 팔이 이 경로로 옛 기록과 비교를 이어간다.
    """
    messages = build_chat_messages(
        context, summary, history, question, snippets, source_bundle
    )
    if tools and execute:
        return _call_loop(
            model=model,
            effort=effort,
            system=CHAT_SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            execute=execute,
        )
    result = _call(
        model=model, effort=effort, system=CHAT_SYSTEM_PROMPT, messages=messages
    )
    # **여기서 막는다. `_call()` 안이 아니다** — 그쪽은 run_summary() 도 쓰는데, 요약이
    # 이 문구로 대체되면 summary_cache 에 그대로 굳어 저장소마다 남는다.
    return {**result, "text": result["text"] or NO_ANSWER}
