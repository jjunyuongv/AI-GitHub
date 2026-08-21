"""대화 메시지 조립. LLM 을 실제로 부르지 않는다 (토큰 절약)."""

from app.services.claude_client import (
    CHAT_SYSTEM_PROMPT,
    MAX_HISTORY_MESSAGES,
    REFUSAL_PHRASES,
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
