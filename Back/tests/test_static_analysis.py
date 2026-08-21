"""정적분석 — 린터 실행과 집계.

**LLM 도 GitHub 도 부르지 않는다.** 린터는 실제로 돌린다(빠르고 무과금이라 대역을 쓸
이유가 없다). 도구가 없는 환경을 위해 그 경로만 따로 검증한다.
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

from app.services import static_analysis

DIRTY = """\
import os
import json


def f():
    unused = 1
    return undefined_name
"""

CLEAN = """\
def add(a, b):
    return a + b
"""


DIRTY_JS = """\
function run() {
  const unused = 1;
  return 2;
}
"""


def _has(tool: str) -> bool:
    return static_analysis.find_tool(tool) is not None


DIRTY_JAVA = """\
package app;

public class Bad {
    public void run() {
        try {
            System.out.println("hi");
        } catch (Exception e) {
        }
    }
}
"""

DIRTY_CSS = """\
.panel {
    color: red;
    color: blue;
}
"""

needs_ruff = pytest.mark.skipif(not _has("ruff"), reason="ruff 가 설치돼 있지 않다")
needs_oxlint = pytest.mark.skipif(not _has("oxlint"), reason="oxlint 가 설치돼 있지 않다")
needs_stylelint = pytest.mark.skipif(
    not _has("stylelint"), reason="stylelint 가 설치돼 있지 않다"
)
needs_pmd = pytest.mark.skipif(
    static_analysis.find_pmd() is None,
    reason="PMD 가 없다 (python scripts/install_pmd.py)",
)


def test_unchecked_languages_return_nothing():
    """검사 대상 언어가 없는 저장소는 **재지 않은 것**이지 깨끗한 것이 아니다.

    (픽스처가 두 번 바뀌었다 — Java 는 PMD 를, CSS 는 stylelint 를 붙이면서 대상이 됐다.
    HTML 은 신호가 있는 도구가 저장소의 JS 설정을 실행해서 일부러 안 붙였다.)
    """
    assert static_analysis.analyze({"b.html": "<p>x</p>", "c.scss": "a { color: red }"}) == []


def test_empty_repo():
    assert static_analysis.analyze({}) == []


@needs_ruff
def test_finds_real_problems():
    results = static_analysis.analyze({"app/bad.py": DIRTY})
    assert len(results) == 1

    r = results[0]
    assert r["tool"] == "ruff"
    assert r["files_checked"] == 1
    codes = {rule["code"] for rule in r["top_rules"]}
    # F401 미사용 import · F841 미사용 지역변수 · F821 정의되지 않은 이름
    assert {"F401", "F841", "F821"} <= codes
    assert r["total"] >= 4


@needs_ruff
def test_clean_code_reports_zero_not_none():
    """**'재 봤더니 0건'과 '재지 않았다'는 다르다.** 화면이 둘을 다르게 말해야 한다."""
    results = static_analysis.analyze({"app/ok.py": CLEAN})
    assert len(results) == 1
    assert results[0]["total"] == 0
    assert results[0]["files_checked"] == 1


@needs_ruff
def test_paths_are_repo_relative():
    """임시 디렉터리 경로가 새어 나가면 프롬프트에 사용자 기기의 경로가 박힌다."""
    results = static_analysis.analyze({"src/deep/nested/bad.py": DIRTY})
    paths = [f["path"] for f in results[0]["top_files"]]
    assert paths == ["src/deep/nested/bad.py"]


@needs_ruff
def test_only_python_files_are_written():
    """다른 언어 파일이 섞여 있어도 ruff 는 파이썬만 센다."""
    results = static_analysis.analyze(
        {"a.py": DIRTY, "b.java": "class B {}", "c.css": "a { color: red }"}
    )
    ruff = next(r for r in results if r["tool"] == "ruff")
    assert ruff["files_checked"] == 1


@needs_oxlint
def test_javascript_is_analyzed():
    results = static_analysis.analyze({"src/app.js": DIRTY_JS})
    assert len(results) == 1
    assert results[0]["tool"] == "oxlint"
    assert results[0]["files_checked"] == 1
    assert results[0]["total"] >= 1
    assert results[0]["top_files"][0]["path"] == "src/app.js"


@needs_ruff
@needs_oxlint
def test_mixed_repo_reports_both_languages():
    results = static_analysis.analyze({"a.py": DIRTY, "b.ts": DIRTY_JS})
    assert {r["tool"] for r in results} == {"ruff", "oxlint"}


@needs_oxlint
def test_repo_cannot_silence_the_linter():
    """**저장소가 심어 둔 린터 설정을 쓰지 않는다.**

    oxlint 는 대상 트리의 `.oxlintrc.json` 을 자동으로 집어 간다. 그대로 두면 저장소가
    설정 하나로 검사를 통째로 끌 수 있다 — 실측에서 122건이 0건이 됐다.
    검사 대상이 검사 결과를 조종하면 리뷰가 성립하지 않는다.
    """
    silencer = '{"categories": {"correctness": "off"}, "rules": {}}'
    with_config = static_analysis.analyze(
        {"src/app.js": DIRTY_JS, ".oxlintrc.json": silencer, "sub/.oxlintrc.js": "module.exports={}"}
    )
    without = static_analysis.analyze({"src/app.js": DIRTY_JS})

    assert with_config[0]["total"] == without[0]["total"]
    assert with_config[0]["files_checked"] == 1, "설정 파일을 검사 대상으로 썼다"


@needs_stylelint
def test_css_is_analyzed():
    results = static_analysis.analyze({"static/app.css": DIRTY_CSS})
    assert len(results) == 1

    r = results[0]
    assert r["tool"] == "stylelint"
    assert r["language"] == "css"
    assert r["files_checked"] == 1
    # 같은 블록에 같은 속성을 두 번 — 뒤엣것이 이기므로 앞의 선언은 죽은 코드다
    assert "declaration-block-no-duplicate-properties" in {c["code"] for c in r["top_rules"]}
    assert r["top_files"][0]["path"] == "static/app.css"


@needs_stylelint
def test_stylelint_output_arrives_on_stderr():
    """**stylelint 는 경고를 찾으면 결과 JSON 을 stderr 로 낸다** (stdout 은 빈다).

    다른 린터와 달라서, stdout 만 읽으면 어떤 저장소든 조용히 0건이 된다.
    실제로 처음에 그렇게 나왔다 — 39개 파일 192건이 0건으로 보였다.
    """
    results = static_analysis.analyze({"a.css": DIRTY_CSS})
    assert results[0]["total"] >= 1


@needs_stylelint
def test_scss_is_not_checked():
    """`.scss` 는 기본 파서가 못 읽는다. 검사 대상에 넣으면 파싱 오류만 쌓인다."""
    assert static_analysis.analyze({"a.scss": DIRTY_CSS}) == []


def test_stylelint_config_is_pinned(monkeypatch):
    """**`--config` 로 우리 규칙을 못박는지 고정한다.**

    stylelint 는 저장소 설정을 자동으로 찾아 쓴다 — 그대로 두면 저장소가 `{"rules": {}}`
    하나로 검사를 통째로 끌 수 있다(실측 1건 → 0건). 이 인자가 곧 방어다.
    (`--config` 를 주면 저장소 설정을 읽지도 실행하지도 않는 것은 별도로 실측했다:
    `.stylelintrc.js` 계열 5종을 심고 부작용을 관찰했으나 실행되지 않았다.)
    """
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        if "--config" in cmd:
            # 호출이 끝나면 지워지는 임시 파일이라 여기서 읽어 둔다
            seen["config"] = Path(cmd[cmd.index("--config") + 1]).read_text(encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(static_analysis, "find_tool", lambda name: "stylelint")
    monkeypatch.setattr(static_analysis.subprocess, "run", fake_run)

    static_analysis.analyze({"a.css": DIRTY_CSS})

    assert "--config" in seen["cmd"]
    assert json.loads(seen["config"])["rules"] == static_analysis.STYLELINT_RULES


@needs_stylelint
def test_repo_cannot_silence_stylelint():
    """저장소가 심어 둔 stylelint 설정이 결과를 바꾸지 못한다.

    여기서 지키는 것은 `_write_sources` 쪽이다 — 설정 파일이 검사 대상 트리에 들어가면
    stylelint 가 그걸 집어 간다. `--config` 로 못박는 것은 위 테스트가 따로 고정한다.
    """
    def css_result(results):
        # 도구로 고른다. 심은 `stylelint.config.js` 는 확장자가 .js 라, 필터가 없으면
        # oxlint 대상이 되어 결과 목록의 순서까지 바뀐다 (인덱스로 집으면 헛짚는다)
        return next(r for r in results if r["tool"] == "stylelint")

    planted = css_result(static_analysis.analyze(
        {
            "a.css": DIRTY_CSS,
            ".stylelintrc.json": '{"rules": {}}',
            "sub/stylelint.config.js": "module.exports = {rules: {}}",
        }
    ))
    plain = css_result(static_analysis.analyze({"a.css": DIRTY_CSS}))

    assert planted["total"] == plain["total"]
    assert planted["files_checked"] == 1, "설정 파일을 검사 대상으로 썼다"


def test_stylelint_rules_exclude_opinions():
    """**관례 규칙을 뺀 상태를 고정한다.**

    실측(39개 파일)에서 recommended 상당 192건 중 155건(81%)이
    `no-descending-specificity` 하나였다. 특이도 순서는 결함이 아니라 관례라,
    이게 들어오면 요약의 경고 수가 관례 지적으로 채워진다.
    """
    assert "no-descending-specificity" not in static_analysis.STYLELINT_RULES
    assert "declaration-block-no-duplicate-properties" in static_analysis.STYLELINT_RULES


@needs_pmd
def test_java_is_analyzed():
    """PMD 는 느려서(JVM 기동 약 2.4초) 실제 실행은 이 한 건으로 족하다."""
    results = static_analysis.analyze({"src/app/Bad.java": DIRTY_JAVA})
    assert len(results) == 1

    r = results[0]
    assert r["tool"] == "pmd"
    assert r["language"] == "java"
    assert r["files_checked"] == 1
    # 빈 catch 블록은 삼킨 예외다 — 리뷰어가 말해야 할 종류
    assert "EmptyCatchBlock" in {rule["code"] for rule in r["top_rules"]}
    assert r["top_files"][0]["path"] == "src/app/Bad.java"


def test_missing_pmd_is_not_an_error(monkeypatch):
    """PMD 는 pip·npm 에 없어 따로 받아야 한다. 없는 환경이 정상 경로다."""
    monkeypatch.setattr(static_analysis, "find_pmd", lambda: None)
    assert static_analysis.analyze({"A.java": DIRTY_JAVA}) == []


def test_pmd_ruleset_excludes_opinions():
    """**의견성 규칙을 뺀 상태를 고정한다.**

    ruff 에서 `UP*`(현대화)를 빼고 `B008`(FastAPI 오탐) 때문에 `B` 를 뺀 것과 같은 기준이다.
    이 목록이 조용히 늘어나면 요약이 스타일 지적으로 채워진다.
    """
    for excluded in ("AvoidDuplicateLiterals", "ReplaceJavaUtilDate"):
        assert f'<exclude name="{excluded}"/>' in static_analysis.PMD_RULESET
    assert "category/java/errorprone.xml" in static_analysis.PMD_RULESET


def test_linter_configs_are_recognized():
    for name in (".oxlintrc.json", ".oxlintrc.js", "eslint.config.js", ".eslintrc.cjs",
                 ".stylelintrc.json", ".stylelintrc.js", "stylelint.config.mjs"):
        assert static_analysis._is_linter_config(name), name
    for name in ("app.js", "config.js", "eslint_helper.js", "stylelint_notes.md"):
        assert not static_analysis._is_linter_config(name), name


def test_rule_set_is_pinned(monkeypatch):
    """**규칙을 명시적으로 넘기는지 고정한다.**

    기본값에 맡기면 도구 버전이 오를 때 요약 내용이 조용히 바뀐다. 실측에서 기본값은
    1,125건(스타일 잡음 위주)인데 고정 세트는 232건 전부가 정합성 신호였다.
    저장소 설정을 무시하는 --isolated 도 함께 본다 — 빠지면 남의 설정이 결과를 바꾼다.
    """
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(static_analysis, "find_tool", lambda name: "ruff")
    monkeypatch.setattr(static_analysis.subprocess, "run", fake_run)

    static_analysis.analyze({"a.py": CLEAN})

    assert "--isolated" in seen["cmd"]
    assert "--select" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--select") + 1] == static_analysis.RUFF_RULES


def test_result_order_follows_runners_not_completion(monkeypatch):
    """**끝난 순서가 아니라 `_RUNNERS` 순서로 담는다.**

    이 집계는 `context` 에 들어가고 그것이 `cache_control` 이 걸린 캐시 접두사다.
    순서가 흔들리면 같은 저장소도 실행마다 바이트가 달라져 **매 질문이 캐시를 새로 쓴다**.
    가장 먼저 제출한 러너를 가장 늦게 끝나게 해서 확인한다.
    """
    def slow(files):
        time.sleep(0.15)
        return {"tool": "slow", "language": "x", "rules_selected": "r",
                "files_checked": 1, "total": 1, "top_rules": [], "top_files": []}

    def fast(files):
        return {"tool": "fast", "language": "y", "rules_selected": "r",
                "files_checked": 1, "total": 1, "top_rules": [], "top_files": []}

    monkeypatch.setattr(static_analysis, "_RUNNERS", (slow, fast))
    assert [r["tool"] for r in static_analysis.analyze({"a.py": "x"})] == ["slow", "fast"]


def test_one_broken_linter_does_not_stop_the_others(monkeypatch):
    """린터 하나가 터져도 나머지 결과는 남아야 한다."""
    def boom(files):
        raise RuntimeError("도구가 죽었다")

    def ok(files):
        return {"tool": "ok", "language": "y", "rules_selected": "r",
                "files_checked": 1, "total": 0, "top_rules": [], "top_files": []}

    monkeypatch.setattr(static_analysis, "_RUNNERS", (boom, ok))
    assert [r["tool"] for r in static_analysis.analyze({"a.py": "x"})] == ["ok"]


def test_missing_tool_is_not_an_error(monkeypatch):
    """도구가 없는 환경에서도 분석은 계속돼야 한다."""
    monkeypatch.setattr(static_analysis, "find_tool", lambda name: None)
    assert static_analysis.analyze({"a.py": DIRTY}) == []


def test_timeout_is_swallowed(monkeypatch):
    """린터가 멈춰도 저장소 분석을 막지 않는다."""
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, static_analysis.TIMEOUT_SECONDS)

    monkeypatch.setattr(static_analysis, "find_tool", lambda name: "ruff")
    monkeypatch.setattr(static_analysis.subprocess, "run", fake_run)
    assert static_analysis.analyze({"a.py": DIRTY}) == []


def test_garbage_output_is_swallowed(monkeypatch):
    """JSON 이 아니면 실패로 본다. exit 1 은 '경고를 찾았다'라 정상이다."""
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="ruff: error", stderr="boom")

    monkeypatch.setattr(static_analysis, "find_tool", lambda name: "ruff")
    monkeypatch.setattr(static_analysis.subprocess, "run", fake_run)
    assert static_analysis.analyze({"a.py": DIRTY}) == []
