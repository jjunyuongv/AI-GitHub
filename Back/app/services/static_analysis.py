"""정적분석 — 저장소 소스에 린터를 돌려 집계를 낸다.

**설정도 의존성도 읽지 않는 린터만 쓴다.** 이 서비스는 임의의 저장소를 받는데,
ESLint 는 `eslint.config.js`(= JS 코드)를 실행하고 의미 있는 결과에는 `npm install`
(= `postinstall` 실행)이 필요하다. Pylint 도 추론 과정에서 모듈을 import 한다.
**남의 코드를 우리 서버에서 실행하는 경로**라 격리 컨테이너 없이는 못 쓴다.

`ruff --isolated` 는 저장소의 `pyproject.toml`·`ruff.toml` 을 무시하고 AST 만 본다.
같은 성격의 JS/TS 도구를 붙이려면 `_RUNNERS` 에 추가한다.

**결과는 집계만 남긴다.** 경고 한 건씩 다 넣으면 큰 저장소는 수천 건이라 프롬프트가
그것으로 찬다. 이 문자열은 스냅샷마다 고정이라 캐시 접두사에 들어간다.
"""

import json
import logging
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)


# npm 도구가 설치되는 곳. `Back/package.json` 의 의존성이 여기로 들어온다.
NODE_BIN = Path(__file__).resolve().parents[2] / "node_modules" / ".bin"


def find_tool(name: str) -> str | None:
    """린터 실행 파일 경로. 없으면 None.

    세 곳을 차례로 본다:
    1. **인터프리터 옆** — `pip install ruff` 는 venv 의 Scripts/bin 에 넣는데, 서버를
       `.venv/Scripts/python.exe -m uvicorn` 처럼 직접 부르면 그 디렉터리가 PATH 에
       없어서 `shutil.which()` 가 못 찾는다 (실제로 그렇게 나왔다)
    2. **`Back/node_modules/.bin`** — `npm install` 이 넣는 곳. 마찬가지로 PATH 에 없다
    3. PATH — 전역 설치를 쓰는 환경을 위해
    """
    for path in (Path(sys.executable).parent, NODE_BIN):
        found = shutil.which(name, path=str(path))
        if found:
            return found
    return shutil.which(name)

# 검사할 규칙. **명시적으로 고정한다** — 기본값에 맡기면 도구 버전이 오를 때
# 요약 내용이 조용히 바뀐다(fastembed 가 pooling 을 바꿨던 것과 같은 함정).
#
# `E9`(문법·런타임 오류) + `F`(pyflakes: 미사용 import·변수, 정의되지 않은 이름).
# 실측(Python 86파일 저장소)에서 기본값은 1,125건인데 대부분 스타일 제안이었고,
# 이 세트는 232건 전부가 정합성 신호였다.
#
# `B`(bugbear)를 넣지 않는 이유: `B008` 90건이 전부 **FastAPI 오탐**이었다
# (`Depends()`·`File()` 을 인자 기본값에 두는 것은 그 프레임워크의 정석이다).
# 오탐을 "결함"이라고 요약에 적으면 조용히 틀린 말을 하게 된다.
RUFF_RULES = "E9,F"

# 린터가 오래 걸릴 이유는 없다(실측 0.03~0.4초). 이 값을 넘으면 뭔가 잘못된 것이므로
# 기다리지 않고 포기한다 — 정적분석은 부가 기능이고 분석을 막으면 안 된다.
TIMEOUT_SECONDS = 60

# 요약에 넣을 상위 개수. 늘리면 토큰만 늘고 "무엇이 많은가"는 이미 앞쪽에서 드러난다.
TOP_RULES = 5
TOP_FILES = 5


def _write_sources(root: Path, files: dict[str, str], suffixes: tuple[str, ...]) -> int:
    """해당 확장자 파일만 임시 디렉터리에 푼다. 쓴 파일 수를 반환.

    린터는 디스크의 경로를 받는다. 한 파일씩 stdin 으로 넘기면 프로세스가 파일 수만큼
    뜨므로, 한 번에 디렉터리로 넘긴다.

    **린터 설정처럼 보이는 파일은 쓰지 않는다.** oxlint 는 대상 트리의 `.oxlintrc.json`
    을 자동으로 찾아 쓰는데, 저장소가 그걸 심어 두면 **검사를 통째로 침묵시킬 수 있다**
    (실측: 122건 → 0건). `--config` 로도 막지만, 애초에 안 쓰는 쪽이 확실하다.
    """
    written = 0
    for path, content in files.items():
        if not path.endswith(suffixes):
            continue
        if _is_linter_config(Path(path).name):
            continue
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written += 1
    return written


def _is_linter_config(name: str) -> bool:
    """린터가 자동으로 집어 갈 만한 설정 파일인가."""
    return name.startswith(
        (".oxlintrc", ".eslintrc", "oxlint.config", "eslint.config",
         ".stylelintrc", "stylelint.config")
    )


def _run_ruff(files: dict[str, str]) -> dict | None:
    """ruff 결과. 파이썬 파일이 없거나 도구가 없으면 None.

    None 과 "경고 0건"은 다르다 — 전자는 '재지 않았다', 후자는 '재 봤더니 깨끗하다'.
    호출부가 그 둘을 구분해 화면에 다르게 쓸 수 있어야 한다.
    """
    tool = find_tool("ruff")
    if not tool:
        logger.info("ruff 가 없어 파이썬 정적분석을 건너뜁니다.")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        checked = _write_sources(root, files, (".py",))
        if not checked:
            return None

        try:
            proc = subprocess.run(
                [
                    tool, "check",
                    "--isolated",   # 저장소의 pyproject.toml·ruff.toml 을 읽지 않는다
                    "--no-cache",   # 임시 경로라 캐시가 쌓일 곳도 의미도 없다
                    "--select", RUFF_RULES,
                    "--output-format", "json",
                    str(root),
                ],
                capture_output=True, text=True, encoding="utf-8",
                timeout=TIMEOUT_SECONDS,
            )
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("ruff 실행에 실패했습니다: %s", e)
            return None

        try:
            findings = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            # exit code 1 은 '경고를 찾았다'라 정상이다. JSON 이 아니면 그때가 진짜 실패다.
            logger.warning("ruff 출력을 읽지 못했습니다: %s", (proc.stderr or proc.stdout)[:200])
            return None

    return _summarize(findings, root, checked, tool="ruff", language="python", rules=RUFF_RULES)


def _summarize(
    findings: list[dict], root: Path, checked: int, *, tool: str, language: str, rules: str
) -> dict:
    """경고 목록을 집계로. 경로는 저장소 기준 상대경로로 되돌린다."""
    codes: Counter[str] = Counter()
    per_file: Counter[str] = Counter()
    messages: dict[str, str] = {}

    for item in findings:
        code = item.get("code") or "?"
        codes[code] += 1
        messages.setdefault(code, item.get("message", ""))
        raw = item.get("filename") or ""
        try:
            per_file[Path(raw).relative_to(root).as_posix()] += 1
        except ValueError:
            per_file[raw] += 1

    return {
        "tool": tool,
        "language": language,
        "rules_selected": rules,
        "files_checked": checked,
        "total": len(findings),
        "top_rules": [
            {"code": code, "count": n, "message": messages[code]}
            for code, n in codes.most_common(TOP_RULES)
        ],
        "top_files": [
            {"path": path, "count": n} for path, n in per_file.most_common(TOP_FILES)
        ],
    }


# JS/TS. oxlint 는 Rust 단일 바이너리라 저장소 의존성을 설치하지 않는다.
#
# **JS 설정 파일은 실행하지 않는다** — `.oxlintrc.js`·`oxlint.config.js` 를 심어 두고
# 부작용(파일 생성)을 관찰했으나 실행되지 않았다. 자동으로 읽는 것은 `.oxlintrc.json`
# 뿐이고 그건 JSON 이라 코드가 아니다.
#
# 다만 그 JSON 하나로 **검사를 통째로 끌 수 있다**(실측 122건 → 0건). 그래서 두 겹으로 막는다:
# `_write_sources` 가 설정 파일을 아예 안 쓰고, 여기서 `--config` 로 우리 규칙을 못박는다.
JS_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")

# ruff 의 `E9,F` 와 같은 성격 — 정합성만 본다. 스타일·현대화 제안은 결함이 아니다.
OXLINT_CONFIG = {"categories": {"correctness": "deny"}}


def _run_oxlint(files: dict[str, str]) -> dict | None:
    """oxlint 결과. JS/TS 파일이 없거나 도구가 없으면 None."""
    tool = find_tool("oxlint")
    if not tool:
        logger.info("oxlint 가 없어 JS/TS 정적분석을 건너뜁니다.")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        checked = _write_sources(root, files, JS_SUFFIXES)
        if not checked:
            return None

        # 설정은 대상 트리 **밖에** 둔다. 안에 두면 그것까지 검사 대상이 된다.
        config = Path(tmp + "-oxlintrc.json")
        try:
            config.write_text(json.dumps(OXLINT_CONFIG), encoding="utf-8")
            proc = subprocess.run(
                [tool, "--config", str(config), "--format", "json", str(root)],
                capture_output=True, text=True, encoding="utf-8",
                timeout=TIMEOUT_SECONDS,
            )
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("oxlint 실행에 실패했습니다: %s", e)
            return None
        finally:
            config.unlink(missing_ok=True)

        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            logger.warning("oxlint 출력을 읽지 못했습니다: %s", (proc.stderr or proc.stdout)[:200])
            return None

        findings = [
            {
                "code": d.get("code") or "?",
                "message": d.get("message", ""),
                "filename": (d.get("labels") or [{}])[0].get("filename")
                or d.get("filename", ""),
            }
            for d in payload.get("diagnostics", [])
        ]

    return _summarize(findings, root, checked, tool="oxlint", language="javascript/typescript",
                      rules="correctness")


# Java. PMD 는 **소스만** 본다 — SpotBugs 류는 바이트코드를 보므로 저장소를 빌드해야 하고,
# 남의 저장소를 빌드하는 것이 곧 임의 코드 실행이라 쓸 수 없다.
#
# pip·npm 에 없어서 `scripts/install_pmd.py` 로 따로 받는다. 없으면 Java 만 건너뛴다.
JAVA_SUFFIXES = (".java",)

PMD_HOME = Path(__file__).resolve().parents[2] / "cache" / "tools"

# 우리 룰셋. **파일로 두지 않고 여기서 만든다** — 코드와 함께 버전 관리되고,
# 저장소가 심어 둔 룰셋을 집어 갈 여지도 없다(oxlint 설정을 같은 이유로 코드에 뒀다).
#
# `errorprone` 을 기준으로 하되 **의견성 규칙을 뺀다.** ruff 에서 `UP*`(현대화 제안)를
# 빼고 `B008`(FastAPI 오탐) 때문에 `B` 를 뺀 것과 같은 기준이다 —
# 스타일·이름·현대화는 결함이 아니고, 그것을 "결함"이라 요약에 적으면 조용히 틀린다.
PMD_RULESET = """<?xml version="1.0"?>
<ruleset name="repodive-java" xmlns="http://pmd.sourceforge.net/ruleset/2.0.0">
  <description>결함 신호만. 스타일·현대화·이름 의견은 제외한다.</description>
  <rule ref="category/java/errorprone.xml">
    <exclude name="AvoidDuplicateLiterals"/>
    <exclude name="ReplaceJavaUtilDate"/>
    <exclude name="AvoidFieldNameMatchingMethodName"/>
    <exclude name="AvoidFieldNameMatchingTypeName"/>
    <exclude name="AvoidLiteralsInIfCondition"/>
  </rule>
</ruleset>
"""

PMD_RULES_LABEL = "errorprone (의견성 규칙 제외)"


def find_pmd() -> str | None:
    """PMD 실행 스크립트. `scripts/install_pmd.py` 가 받아 둔 것을 찾는다.

    이름 하나로 찾을 수 없어(`cache/tools/pmd-bin-<버전>/bin/pmd`) `find_tool` 과 따로 둔다.
    여러 버전이 있으면 가장 최신 이름을 쓴다.
    """
    name = "pmd.bat" if sys.platform == "win32" else "pmd"
    found = sorted(PMD_HOME.glob(f"pmd-bin-*/bin/{name}"))
    return str(found[-1]) if found else None


def _run_pmd(files: dict[str, str]) -> dict | None:
    """PMD 결과. Java 파일이 없거나 도구가 없으면 None."""
    tool = find_pmd()
    if not tool:
        logger.info("PMD 가 없어 Java 정적분석을 건너뜁니다 (scripts/install_pmd.py).")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        checked = _write_sources(root, files, JAVA_SUFFIXES)
        if not checked:
            return None

        # 룰셋은 대상 트리 **밖에** 둔다. 안에 두면 그것까지 검사 대상이 된다.
        ruleset = Path(tmp + "-ruleset.xml")
        try:
            ruleset.write_text(PMD_RULESET, encoding="utf-8")
            proc = subprocess.run(
                [tool, "check", "-d", str(root), "-R", str(ruleset),
                 "-f", "json", "--no-cache", "--no-progress"],
                capture_output=True, text=True, encoding="utf-8",
                timeout=TIMEOUT_SECONDS,
            )
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("PMD 실행에 실패했습니다: %s", e)
            return None
        finally:
            ruleset.unlink(missing_ok=True)

        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            # exit 4 는 '위반을 찾았다'라 정상이다. JSON 이 아니면 그때가 진짜 실패다.
            logger.warning("PMD 출력을 읽지 못했습니다: %s", (proc.stderr or proc.stdout)[:200])
            return None

        findings = [
            {
                "code": v.get("rule") or "?",
                "message": v.get("description", ""),
                "filename": entry.get("filename", ""),
            }
            for entry in payload.get("files", [])
            for v in entry.get("violations", [])
        ]

    return _summarize(findings, root, checked, tool="pmd", language="java",
                      rules=PMD_RULES_LABEL)


# CSS. **`.css` 만 본다** — `.scss` 는 기본 파서가 읽지 못해(`//` 주석 등) 파싱 오류가
# 나고, 읽히게 하려면 커스텀 syntax 의존성이 하나 더 붙는다.
#
# 저장소 설정을 실행하는가: **`--config` 를 주면 읽지도 실행하지도 않는다.** `.stylelintrc.js`
# 계열 5종을 심고 부작용(파일 생성)을 관찰했으나 마커가 생기지 않았고 경고 건수도 그대로였다.
# 반대로 `--config` 없이 두면 저장소 설정이 검사를 통째로 끈다 — 그래서 선택이 아니라 필수다.
CSS_SUFFIXES = (".css",)

# **결함성 규칙만.** ruff 의 `E9,F`·oxlint 의 `correctness` 와 같은 성격이다.
# CSS 는 다른 언어보다 '결함' 개념이 약해서 선별이 더 중요했다 — 실측(39개 파일):
#
#   recommended 상당 192건 중 **155건(81%)이 `no-descending-specificity`** 하나였다.
#   특이도 순서 관례라 결함이 아니다. 그것을 "경고"라고 요약에 적으면 조용히 틀린다.
#   남긴 세트는 37건이고 내용도 실수 쪽이었다(shorthand `margin` 이 앞의 `margin-bottom`
#   을 덮음, 같은 셀렉터를 18행과 178행에 두 번).
#
# unknown 계열은 실측 저장소에서 0건이었지만 넣어 둔다 — 오타·잘못된 값은 명백한 결함이고
# 오탐이 사실상 없다.
STYLELINT_RULES = {
    "declaration-block-no-duplicate-properties": True,
    "declaration-block-no-shorthand-property-overrides": True,
    "no-duplicate-selectors": True,
    "color-no-invalid-hex": True,
    "unit-no-unknown": True,
    "property-no-unknown": True,
    "function-no-unknown": True,
    "media-feature-name-no-unknown": True,
    "selector-pseudo-class-no-unknown": True,
    "selector-pseudo-element-no-unknown": True,
    "named-grid-areas-no-invalid": True,
    "custom-property-no-missing-var-function": True,
    "no-invalid-double-slash-comments": True,
    "string-no-newline": True,
}

# oxlint 의 `correctness` 와 같은 성격이라는 뜻. stylelint 에는 그런 이름의 세트가 없어
# 우리가 골랐다는 사실이 프롬프트에 드러나게 적는다.
STYLELINT_RULES_LABEL = "correctness 상당 (특이도·스타일 관례 제외)"


def _run_stylelint(files: dict[str, str]) -> dict | None:
    """stylelint 결과. CSS 파일이 없거나 도구가 없으면 None."""
    tool = find_tool("stylelint")
    if not tool:
        logger.info("stylelint 가 없어 CSS 정적분석을 건너뜁니다.")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        checked = _write_sources(root, files, CSS_SUFFIXES)
        if not checked:
            return None

        # 설정은 대상 트리 **밖에** 둔다. 안에 두면 그것까지 검사 대상이 된다.
        config = Path(tmp + "-stylelintrc.json")
        try:
            config.write_text(json.dumps({"rules": STYLELINT_RULES}), encoding="utf-8")
            proc = subprocess.run(
                [tool, "**/*.css", "--config", str(config),
                 "--formatter", "json", "--no-color"],
                cwd=str(root),  # glob 기준. 절대경로 glob 은 Windows 에서 어긋난다
                capture_output=True, text=True, encoding="utf-8",
                timeout=TIMEOUT_SECONDS,
            )
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("stylelint 실행에 실패했습니다: %s", e)
            return None
        finally:
            config.unlink(missing_ok=True)

        # **경고를 찾으면 결과 JSON 을 stderr 로 낸다** (그때 stdout 은 빈다).
        # 다른 린터와 달라서 stdout 만 보면 늘 0건으로 읽힌다 — 실제로 그렇게 나왔다.
        raw = proc.stdout.strip() or proc.stderr.strip()
        try:
            payload = json.loads(raw or "[]")
        except json.JSONDecodeError:
            logger.warning("stylelint 출력을 읽지 못했습니다: %s", raw[:200])
            return None

        findings = [
            {
                "code": w.get("rule") or "?",
                # 메시지 끝에 규칙명이 괄호로 또 붙는다 — code 와 겹치니 뗀다
                "message": w.get("text", "").rsplit(" (", 1)[0],
                "filename": entry.get("source", ""),
            }
            for entry in payload
            for w in entry.get("warnings", [])
        ]

    return _summarize(findings, root, checked, tool="stylelint", language="css",
                      rules=STYLELINT_RULES_LABEL)


# 언어별 실행기. 언어를 늘릴 때 여기에 추가한다.
#
# **HTML 은 뺐다.** 신호가 있는 도구(html-validate)가 우리가 `--config` 로 규칙을 못박아도
# 저장소의 `.htmlvalidate.js`·`.cjs` 를 **실행했고**, 검사도 침묵당했다(2건 → 0건).
# ESLint·Pylint 를 뺀 것과 같은 이유다. htmlhint 는 안전성 이전에 신호가 5건뿐이었다.
_RUNNERS = (_run_ruff, _run_oxlint, _run_pmd, _run_stylelint)


def analyze(files: dict[str, str]) -> list[dict]:
    """저장소 소스의 정적분석 집계. 잰 것이 없으면 빈 목록.

    **언어별 린터를 함께 돌린다.** 셋 다 subprocess 를 기다리는 일이라(GIL 을 놓는다)
    스레드로 충분하다. 순차로 돌리면 합이 되는데, PMD 의 JVM 기동 2.4초가 그 합을
    지배한다 — 같이 돌리면 가장 느린 하나로 줄어든다.

    **결과 순서는 `_RUNNERS` 순서로 고정한다.** 이 집계는 `context` 에 들어가고 그것이
    곧 `cache_control` 이 걸린 캐시 접두사다 — 끝난 순서대로 담으면 같은 저장소도
    실행마다 바이트가 달라져 **매 질문이 캐시를 새로 쓴다**
    (`build_source_bundle` 이 경로 순으로 정렬하는 것과 같은 이유다).

    **실패해도 예외를 올리지 않는다** — 정적분석이 안 돼서 저장소 분석 자체가
    실패하면 안 된다(세션 생성·색인 시작과 같은 방침).
    """
    with ThreadPoolExecutor(max_workers=len(_RUNNERS)) as pool:
        futures = [(run, pool.submit(run, files)) for run in _RUNNERS]

        results = []
        for run, future in futures:  # 제출 순서대로 거둔다 (완료 순서가 아니라)
            try:
                result = future.result()
            except Exception as e:
                logger.warning("정적분석 중 오류 (%s): %s", run.__name__, e)
                continue
            if result:
                results.append(result)
    return results
