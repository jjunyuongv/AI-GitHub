"""대화 메시지 조립과 도구 루프. LLM 을 실제로 부르지 않는다 (토큰 절약).

루프는 SDK 응답을 대역으로 갈아끼워 돈다 — 네트워크도 API 키도 필요 없다.
"""

from types import SimpleNamespace

import pytest

from app.services import claude_client
from app.services.claude_client import (
    CHAT_SYSTEM_PROMPT,
    MAX_HISTORY_MESSAGES,
    REFUSAL_PHRASES,
    billable_tokens,
    build_chat_messages,
)

CONTEXT = "## 레포지토리 정보\n- 이름: React/React"
SUMMARY = "요약 본문"


def _history(pairs: int) -> list[dict]:
    messages = []
    for i in range(pairs):
        messages.append({"role": "user", "content": f"질문{i}"})
        messages.append({"role": "assistant", "content": f"답변{i}"})
    return messages


def test_prologue_is_context_then_summary():
    messages = build_chat_messages(CONTEXT, SUMMARY, [], "인증은 어디서 처리해?")

    assert messages[0]["role"] == "user"
    assert messages[0]["content"][0]["text"] == CONTEXT
    assert messages[1] == {"role": "assistant", "content": SUMMARY}


def test_snapshot_block_carries_the_cache_breakpoint():
    """캐시 지점은 스냅샷 원문에 걸어야 한다 — 대화가 길어져도 그 앞은 캐시에서 읽힌다."""
    messages = build_chat_messages(CONTEXT, SUMMARY, _history(3), "질문")

    assert messages[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    # 캐시 지점이 하나뿐인지 (뒤쪽 메시지에 또 붙으면 캐시가 갈린다)
    marked = [m for m in messages if isinstance(m["content"], list)]
    assert len(marked) == 1


def test_question_comes_last():
    messages = build_chat_messages(CONTEXT, SUMMARY, _history(2), "마지막 질문")

    assert messages[-1] == {"role": "user", "content": "마지막 질문"}


SNIPPETS = "## 질문과 관련된 코드\n\n### SecurityConfig.java (26-91행)\n```java\n@Bean\n```"


def test_snippets_go_into_the_last_message_only():
    """검색된 코드는 질문마다 달라진다. 캐시 지점(첫 메시지)에 넣으면 매 질문이
    캐시를 깨뜨려 스냅샷 전체를 정가로 다시 계산하게 된다."""
    messages = build_chat_messages(CONTEXT, SUMMARY, _history(2), "질문", SNIPPETS)

    # 스냅샷 블록은 코드가 섞이지 않은 원문 그대로여야 한다
    assert messages[0]["content"][0]["text"] == CONTEXT
    assert "SecurityConfig" not in messages[0]["content"][0]["text"]

    last = messages[-1]
    assert last["role"] == "user"
    assert SNIPPETS in last["content"]
    assert last["content"].endswith("질문")


def test_snippets_do_not_change_the_cache_breakpoint():
    """스니펫이 있든 없든 캐시가 걸리는 위치와 개수는 같아야 한다."""
    without = build_chat_messages(CONTEXT, SUMMARY, _history(2), "질문")
    with_code = build_chat_messages(CONTEXT, SUMMARY, _history(2), "질문", SNIPPETS)

    assert without[0] == with_code[0]
    assert len([m for m in with_code if isinstance(m["content"], list)]) == 1


def test_no_snippets_leaves_the_question_untouched():
    """검색 결과가 없을 때 구분선이나 빈 줄이 붙으면 안 된다."""
    messages = build_chat_messages(CONTEXT, SUMMARY, [], "질문")

    assert messages[-1] == {"role": "user", "content": "질문"}


BUNDLE = "## 저장소 전체 소스\n\n### app/main.py\n```python\n1|def run(): pass\n```"


def test_source_bundle_goes_inside_the_cached_prefix():
    """소스 전체는 스냅샷마다 고정이라 캐시 접두사에 들어가야 한다.

    질문 뒤에 붙이면 매 질문이 정가로 계산된다 — 스니펫과 정확히 반대다.
    """
    messages = build_chat_messages(
        CONTEXT, SUMMARY, _history(2), "질문", source_bundle=BUNDLE
    )

    cached = messages[0]["content"][0]
    assert cached["cache_control"] == {"type": "ephemeral"}
    assert BUNDLE in cached["text"]
    assert cached["text"].startswith(CONTEXT)
    assert messages[-1] == {"role": "user", "content": "질문"}


def test_source_bundle_does_not_add_a_second_breakpoint():
    """브레이크포인트가 갈리면 접두사 하나가 캐시 밖으로 나간다."""
    messages = build_chat_messages(
        CONTEXT, SUMMARY, _history(2), "질문", source_bundle=BUNDLE
    )

    assert len([m for m in messages if isinstance(m["content"], list)]) == 1


def test_empty_bundle_leaves_the_snapshot_block_byte_identical():
    """RAG 경로는 지금까지와 한 바이트도 달라지면 안 된다 — 달라지면 옛 캐시가 통째로 깨진다."""
    rag = build_chat_messages(CONTEXT, SUMMARY, _history(2), "질문", SNIPPETS)
    before = build_chat_messages(CONTEXT, SUMMARY, _history(2), "질문", SNIPPETS, "")

    assert rag == before
    assert before[0]["content"][0]["text"] == CONTEXT


def test_roles_alternate():
    """역할이 번갈아 나오지 않으면 API 가 호출을 거부한다."""
    messages = build_chat_messages(CONTEXT, SUMMARY, _history(4), "질문")

    roles = [m["role"] for m in messages]
    assert roles[0] == "user"
    assert all(a != b for a, b in zip(roles, roles[1:]))


def test_old_turns_are_dropped_first():
    messages = build_chat_messages(CONTEXT, SUMMARY, _history(20), "새 질문")

    # 프롤로그 2개 + 이력 MAX_HISTORY_MESSAGES개 + 새 질문 1개
    assert len(messages) == MAX_HISTORY_MESSAGES + 3
    kept = [m["content"] for m in messages[2:-1]]
    assert kept[0] == "질문10"  # 40개 중 최근 20개만 남는다
    assert kept[-1] == "답변19"


def test_short_history_is_kept_whole():
    messages = build_chat_messages(CONTEXT, SUMMARY, _history(1), "질문")

    assert [m["content"] for m in messages[2:-1]] == ["질문0", "답변0"]


def test_refusal_phrases_are_in_the_chat_prompt():
    """거절 문구 상수와 프롬프트가 갈라지지 않는가.

    답변 품질 하네스는 이 문구를 **문자열로 찾아** 거절 여부를 채점한다. 프롬프트 쪽
    표현만 바뀌면 모델은 여전히 옳게 거절하는데 하네스는 전부 실패로 세게 된다 —
    조용히 틀리는 종류라 여기서 잡는다. 프롬프트를 고칠 때는 상수도 같이 고칠 것.
    """
    missing = [p for p in REFUSAL_PHRASES if p not in CHAT_SYSTEM_PROMPT]

    assert not missing, (
        f"거절 문구가 CHAT_SYSTEM_PROMPT 에 없다: {missing}."
        " 프롬프트를 고쳤다면 claude_client 의 상수도 같이 고칠 것"
    )


def test_extra_message_fields_are_not_forwarded():
    """DB 행에는 id·created_at 도 있다. API 가 모르는 키를 보내면 거부한다."""
    history = [{"role": "user", "content": "질문", "id": 1, "created_at": "2026-08-15"}]

    messages = build_chat_messages(CONTEXT, SUMMARY, history, "새 질문")

    assert messages[2] == {"role": "user", "content": "질문"}


# ── 도구 루프 ────────────────────────────────────────────────
#
# SDK 응답을 대역으로 만든다. 실제 호출은 하지 않으므로 무과금이고 API 키도 필요 없다.


def _text(value: str):
    return SimpleNamespace(type="text", text=value)


def _use(tool_id: str, name: str, params: dict):
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=params)


def _reply(blocks, stop_reason, tokens=10):
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=tokens,
            output_tokens=tokens,
            cache_creation_input_tokens=tokens,
            cache_read_input_tokens=tokens,
        ),
    )


@pytest.fixture
def fake_api(monkeypatch):
    """정해진 응답을 차례로 내주는 SDK 대역. 보낸 params 를 전부 기록한다."""
    def install(replies):
        sent = []

        def fake_raw(*, model, effort, system, messages, tools=None):
            sent.append({"messages": [*messages], "tools": tools, "system": system})
            reply = replies[len(sent) - 1]
            return reply, {
                "llm_ms": 100,
                "input_tokens": reply.usage.input_tokens,
                "output_tokens": reply.usage.output_tokens,
                "cache_write_tokens": reply.usage.cache_creation_input_tokens,
                "cache_read_tokens": reply.usage.cache_read_input_tokens,
            }

        monkeypatch.setattr(claude_client, "_raw_call", fake_raw)
        return sent

    return install


TOOLS = [{"name": "search_code", "input_schema": {}}]


def _run(execute=None, **kw):
    return claude_client._call_loop(
        model="claude-sonnet-5",
        effort="medium",
        system=CHAT_SYSTEM_PROMPT,
        messages=build_chat_messages(CONTEXT, SUMMARY, [], "질문"),
        tools=TOOLS,
        execute=execute or (lambda name, params: "도구 결과"),
        **kw,
    )


def test_loop_runs_tool_then_answers(fake_api):
    sent = fake_api([
        _reply([_use("t1", "search_code", {"query": "인증"})], "tool_use"),
        _reply([_text("인증은 SecurityConfig 에 있습니다.")], "end_turn"),
    ])

    result = _run()

    assert result["text"] == "인증은 SecurityConfig 에 있습니다."
    assert result["round_trips"] == 1
    assert len(sent) == 2


def test_tool_result_goes_back_with_its_id(fake_api):
    sent = fake_api([
        _reply([_use("t1", "search_code", {"query": "인증"})], "tool_use"),
        _reply([_text("답")], "end_turn"),
    ])

    _run(execute=lambda name, params: f"{name} 결과")

    followup = sent[1]["messages"][-1]
    assert followup["role"] == "user"
    assert followup["content"][0]["tool_use_id"] == "t1"
    assert followup["content"][0]["content"] == "search_code 결과"
    assert followup["content"][0]["is_error"] is False


def test_parallel_tool_uses_come_back_in_one_message(fake_api):
    """나눠 보내면 모델이 병렬 호출을 그만두게 학습된다."""
    sent = fake_api([
        _reply(
            [_use("t1", "grep", {"pattern": "a"}), _use("t2", "grep", {"pattern": "b"})],
            "tool_use",
        ),
        _reply([_text("답")], "end_turn"),
    ])

    _run()

    followup = sent[1]["messages"][-1]
    assert len(followup["content"]) == 2
    assert [b["tool_use_id"] for b in followup["content"]] == ["t1", "t2"]


def test_a_failing_tool_is_returned_as_an_error_not_dropped(fake_api):
    """빠뜨리면 API 가 짝 없는 tool_use 를 거부한다."""
    def boom(name, params):
        raise RuntimeError("터졌다")

    sent = fake_api([
        _reply([_use("t1", "grep", {"pattern": "a"})], "tool_use"),
        _reply([_text("답")], "end_turn"),
    ])

    result = _run(execute=boom)

    block = sent[1]["messages"][-1]["content"][0]
    assert block["is_error"] is True
    assert "터졌다" in block["content"]
    assert result["text"] == "답"


def test_usage_is_summed_across_every_call(fake_api):
    """**마지막 호출만 세면 일일 상한이 사실상 꺼진다.**"""
    fake_api([
        _reply([_use("t1", "grep", {"pattern": "a"})], "tool_use", tokens=10),
        _reply([_use("t2", "grep", {"pattern": "b"})], "tool_use", tokens=20),
        _reply([_text("답")], "end_turn", tokens=30),
    ])

    result = _run()

    assert result["round_trips"] == 2
    assert result["input_tokens"] == 60
    assert result["output_tokens"] == 60
    assert result["cache_write_tokens"] == 60
    assert result["cache_read_tokens"] == 60
    assert result["llm_ms"] == 300


def test_billable_tokens_counts_every_call(fake_api):
    """rate_limit 이 이 값으로 일일 상한을 센다. 합이 아니면 상한이 새 나간다."""
    fake_api([
        _reply([_use("t1", "grep", {"pattern": "a"})], "tool_use", tokens=10),
        _reply([_text("답")], "end_turn", tokens=30),
    ])

    assert billable_tokens(_run()) == 160  # (10+30) × 4종


def test_result_keeps_the_shape_run_log_expects(fake_api):
    """append_run 은 run_summary 결과 모양을 그대로 받는다. 키가 빠지면 KeyError 다."""
    fake_api([_reply([_text("답")], "end_turn")])

    result = _run()

    assert set(result) >= {
        "text", "llm_ms", "input_tokens", "output_tokens",
        "cache_write_tokens", "cache_read_tokens", "cost_usd",
    }


def test_round_trip_cap_stops_the_loop(fake_api):
    """한도를 넘겨 계속 부르면 끊는다. 안 끊으면 비용이 이차로 는다."""
    replies = [
        _reply([_use(f"t{i}", "grep", {"pattern": "a"})], "tool_use")
        for i in range(claude_client.MAX_TOOL_ROUND_TRIPS + 3)
    ]
    sent = fake_api(replies)

    result = _run()

    assert result["round_trips"] == claude_client.MAX_TOOL_ROUND_TRIPS
    assert result["hit_round_trip_cap"] is True
    assert len(sent) == claude_client.MAX_TOOL_ROUND_TRIPS + 1


def test_the_cap_notice_rides_the_tail_not_tool_choice(fake_api):
    """**tool_choice 를 건드리면 messages 캐시가 무효화된다.**

    안내는 마지막 사용자 메시지 꼬리에 붙어야 접두사가 그대로 살아 있다.
    """
    replies = [
        _reply([_use(f"t{i}", "grep", {"pattern": "a"})], "tool_use")
        for i in range(claude_client.MAX_TOOL_ROUND_TRIPS)
    ] + [_reply([_text("정리한 답")], "end_turn")]
    sent = fake_api(replies)

    result = _run()

    last = sent[-1]["messages"][-1]["content"]
    assert last[-1] == {"type": "text", "text": claude_client.ROUND_TRIP_CAP_NOTICE}
    assert result["text"] == "정리한 답"
    assert result["hit_round_trip_cap"] is True


def test_no_notice_before_the_cap(fake_api):
    """한도 전에 안내가 붙으면 모델이 일찍 포기한다."""
    sent = fake_api([
        _reply([_use("t1", "grep", {"pattern": "a"})], "tool_use"),
        _reply([_text("답")], "end_turn"),
    ])

    _run()

    blocks = sent[1]["messages"][-1]["content"]
    assert all(b["type"] == "tool_result" for b in blocks)


def test_empty_answer_after_tools_is_not_blank(fake_api):
    """빈 말풍선이 뜨고 왜인지 아무 데도 안 남는 상태를 막는다."""
    replies = [
        _reply([_use(f"t{i}", "grep", {"pattern": "a"})], "tool_use")
        for i in range(claude_client.MAX_TOOL_ROUND_TRIPS + 1)
    ]
    fake_api(replies)

    assert _run()["text"] == claude_client.NO_ANSWER_AFTER_TOOLS


def test_cache_breakpoints_survive_the_loop(fake_api):
    """루프가 돈 뒤에도 브레이크포인트는 system 1 + messages[0] 1 이어야 한다.

    꼬리에 또 걸면 쓰기 1.25배가 R=3 에서 이득을 먹는다.
    """
    sent = fake_api([
        _reply([_use("t1", "grep", {"pattern": "a"})], "tool_use"),
        _reply([_use("t2", "grep", {"pattern": "b"})], "tool_use"),
        _reply([_text("답")], "end_turn"),
    ])

    _run()

    messages = sent[-1]["messages"]
    marked = [
        block
        for m in messages
        if isinstance(m["content"], list)
        for block in m["content"]
        if isinstance(block, dict) and "cache_control" in block
    ]
    assert len(marked) == 1


def test_tools_are_identical_on_every_call(fake_api):
    """tools 는 렌더 위치 0 이다. 호출마다 달라지면 캐시 접두사가 갈린다."""
    sent = fake_api([
        _reply([_use("t1", "grep", {"pattern": "a"})], "tool_use"),
        _reply([_text("답")], "end_turn"),
    ])

    _run()

    assert sent[0]["tools"] == sent[1]["tools"] == TOOLS


def test_per_call_usage_is_kept_not_only_the_sum(fake_api):
    """합계만 남기면 산식의 aᵢ 를 사후에 못 되살린다 — 지금 상한은 그 추정 위에 서 있다."""
    fake_api([
        _reply([_use("t1", "grep", {"pattern": "a"})], "tool_use", tokens=10),
        _reply([_text("답")], "end_turn", tokens=30),
    ])

    result = _run()

    assert [c["output_tokens"] for c in result["calls"]] == [10, 30]
    assert [c["stop_reason"] for c in result["calls"]] == ["tool_use", "end_turn"]


def test_tool_trace_is_carried_out_with_round_numbers(fake_api):
    """실행기가 남긴 내역에 라운드 번호를 찍어 함께 돌려준다."""
    def execute(name, params):
        execute.trace.append({"tool": name, "input": params, "caps": []})
        return "결과"

    execute.trace = []
    fake_api([
        _reply([_use("t1", "grep", {"pattern": "a"})], "tool_use"),
        _reply([_use("t2", "read_file", {"path": "a.py"})], "tool_use"),
        _reply([_text("답")], "end_turn"),
    ])

    result = _run(execute=execute)

    assert [e["tool"] for e in result["tool_trace"]] == ["grep", "read_file"]
    assert [e["round"] for e in result["tool_trace"]] == [1, 2]


def test_a_traceless_executor_still_works(fake_api):
    """대역 실행기는 내역을 안 남긴다. 루프가 그것에 기대면 안 된다."""
    fake_api([
        _reply([_use("t1", "grep", {"pattern": "a"})], "tool_use"),
        _reply([_text("답")], "end_turn"),
    ])

    result = _run()

    assert result["tool_trace"] == []
    assert result["text"] == "답"


def test_no_tool_use_means_no_round_trips(fake_api):
    fake_api([_reply([_text("바로 답")], "end_turn")])

    result = _run()

    assert result["round_trips"] == 0
    assert result["hit_round_trip_cap"] is False
    assert result["text"] == "바로 답"


# --- 텍스트 없이 끝난 응답 ---------------------------------------------------


def _thinking():
    """text 블록 없이 온 응답의 실제 모양.

    `thinking` 을 안 보내도 sonnet-5 는 adaptive 로 돌고, display 기본값이 "omitted" 라
    그 블록의 text 가 빈 문자열이다. 실측으로 출력 15~16토큰이 여기에만 있었다.
    """
    return SimpleNamespace(type="thinking", thinking="")


def _chat_without_tools():
    return claude_client.run_chat(CONTEXT, SUMMARY, [], "질문")


def test_a_textless_answer_is_not_blank_without_tools(fake_api):
    """**도구를 안 붙인 경로에서 실제로 빈 답변이 나갔다.** 화면에 빈 말풍선만 남고
    에러도 안 떠서 사용자는 이유를 알 수 없었다."""
    fake_api([_reply([_thinking()], "end_turn")])

    assert _chat_without_tools()["text"] == claude_client.NO_ANSWER


def test_a_real_answer_is_left_alone(fake_api):
    """폴백이 정상 답변까지 덮으면 안 된다 (뒤쪽이 진짜 방어선이다)."""
    fake_api([_reply([_text("진짜 답")], "end_turn")])

    assert _chat_without_tools()["text"] == "진짜 답"


def test_the_empty_answer_notice_matches_the_path(fake_api):
    """도구를 **안 쓴** 건에 "도구를 여러 번 불렀지만" 이라고 하면 거짓말이 된다.

    두 문구를 하나로 합치면 이 테스트가 깨진다.
    """
    fake_api([_reply([_thinking()], "end_turn")])

    text = _run()["text"]

    assert text == claude_client.NO_ANSWER
    assert text != claude_client.NO_ANSWER_AFTER_TOOLS


def test_stop_reason_rides_along(fake_api):
    """**두 값을 다 검사한다** — 한쪽만 보면 문자열을 박아 넣어도 통과한다.

    빈 답변이 refusal 이었는지 end_turn 이었는지는 이 값으로만 갈린다.
    """
    fake_api([_reply([_text("답")], "end_turn")])
    assert _chat_without_tools()["stop_reason"] == "end_turn"

    fake_api([_reply([_thinking()], "refusal")])
    assert _chat_without_tools()["stop_reason"] == "refusal"


def test_the_loop_reports_the_last_stop_reason(fake_api):
    """첫 호출 값을 실으면 도구를 쓴 건이 전부 "tool_use" 로 남는다."""
    fake_api([
        _reply([_use("t1", "grep", {"pattern": "a"})], "tool_use"),
        _reply([_text("답")], "refusal"),
    ])

    assert _run()["stop_reason"] == "refusal"
