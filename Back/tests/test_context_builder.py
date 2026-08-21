"""전체 주입용 소스 번들 조립. LLM 을 부르지 않는다 (순수 문자열 조립)."""

from app.services.context_builder import (
    CHARS_PER_TOKEN,
    build_context,
    build_source_bundle,
    estimate_tokens,
)

FILES = {
    "src/main/java/App.java": "class App {\n  void run() {}\n}",
    "app/util.py": "def add(a, b):\n    return a + b",
}

CTX = {
    "meta": {
        "owner": "o", "name": "n", "description": None,
        "primary_language": "Python", "stars": 1,
    },
    "readme": "",
    "manifests": {},
    "file_paths": ["app/util.py"],
}

ANALYSIS = [{
    "tool": "ruff", "language": "python", "rules_selected": "E9,F",
    "files_checked": 86, "total": 232,
    "top_rules": [{"code": "F401", "count": 86, "message": "imported but unused"}],
    "top_files": [{"path": "app/util.py", "count": 9}],
}]


def test_analysis_section_is_absent_when_nothing_was_measured():
    """**재지 않았으면 섹션 자체가 없어야 한다.**

    빈 섹션을 남기면 모델이 "정적분석 결과 문제 없음"으로 읽는다 — 파이썬이 없어
    못 잰 저장소와 깨끗한 저장소가 같은 모양이 된다.
    """
    assert "## 정적분석" not in build_context(CTX)
    assert "## 정적분석" not in build_context(CTX, analysis=[])


def test_analysis_section_states_what_was_checked():
    """검사 대상(언어·규칙)을 밝혀야 모델이 범위를 넘겨 말하지 않는다."""
    text = build_context(CTX, analysis=ANALYSIS)
    assert "## 정적분석" in text
    assert "python" in text and "E9,F" in text
    assert "86개 파일 검사" in text and "232건" in text
    assert "F401" in text
    assert "검사하지 않은 언어" in text


def test_analysis_section_is_small():
    """집계만 넣는다. 이 블록은 캐시 접두사에 들어가지만 그래도 작아야 한다."""
    only_analysis = build_context(CTX, analysis=ANALYSIS).split("## 정적분석")[1]
    assert len(only_analysis) < 1000


def test_bundle_is_ordered_by_path():
    """딕셔너리 순서(tarball 순서)에 맡기면 같은 저장소도 실행마다 바이트가 달라진다.

    이 문자열은 cache_control 이 걸리는 캐시 접두사라, 순서가 흔들리면 매 질문이
    캐시를 새로 쓴다 — 우회의 비용 계산이 통째로 무너진다.
    """
    forward = build_source_bundle(FILES)
    reversed_insertion = build_source_bundle(dict(reversed(list(FILES.items()))))

    assert forward == reversed_insertion
    assert forward.index("app/util.py") < forward.index("src/main/java/App.java")


def test_lines_are_numbered_from_one():
    """CHAT_SYSTEM_PROMPT 가 '몇 행인지 밝히라'고 요구한다. 번호가 없으면 지어낸다."""
    bundle = build_source_bundle({"app/util.py": FILES["app/util.py"]})

    assert "1|def add(a, b):" in bundle
    assert "2|    return a + b" in bundle


def test_language_tag_comes_from_the_extension():
    bundle = build_source_bundle(FILES)

    assert "```java" in bundle
    assert "```python" in bundle


def test_unknown_extension_gets_an_empty_tag():
    """언어를 모른다고 파일을 버리지 않는다 — 내용은 여전히 답의 근거가 된다."""
    bundle = build_source_bundle({"Makefile.unknown": "all:\n\techo hi"})

    assert "```\n1|all:" in bundle


def test_empty_repo_makes_an_empty_bundle():
    """소스가 없으면 빈 문자열이다. 머리말만 남기면 캐시 최소 길이만 축내고 근거는 없다."""
    assert build_source_bundle({}) == ""


def test_fallback_estimate_overcounts_rather_than_under():
    """실측 문자/토큰 비율은 2.05~2.41 이었다. 대체값 2.0 은 그보다 낮아야 한다.

    낮아야 토큰을 실제보다 **많게** 잡고, 우회를 덜 켜는 쪽으로 틀린다.
    반대로 틀리면 임계값을 넘는 저장소가 우회로 새어 비용이 초과된다.
    """
    assert CHARS_PER_TOKEN <= 2.05

    text = "x" * 1000
    assert estimate_tokens(text) >= round(len(text) / 2.05)
