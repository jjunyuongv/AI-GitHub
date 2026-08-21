"""STATUS.md 가 코드와 어긋나지 않는가.

STATUS.md 는 "폐기된 결정을 현행으로 착각하는 것"을 막으려고 만든 문서다. **그 문서가
낡으면 목적이 정확히 뒤집힌다** — 틀린 값을 권위 있게 말하는 문서가 되어, 로그를 직접
읽는 것보다 나빠진다. 쓰는 순간에는 항상 정확하고 처음 틀리는 순간에는 아무도 모르므로,
사람의 성실함에 맡기지 않고 여기서 잰다.

**무과금이다.** config.py 는 AST 로 읽고(모듈 import 조차 하지 않는다) 나머지 상수는
import 로 얻는다. 임베딩 모델을 올리거나 DB 에 접속하거나 LLM 을 부르는 경로가 없다.

`test_config.py` 와 겹치지 않는다 — 그쪽은 `.env.example` ↔ `config.py` 를 대조하고,
여기는 STATUS.md ↔ 코드를 대조한다. env 키 검사도 방향이 다르다: 문서가 적어 둔 키가
config.py 에 실제로 있는지를 본다.

**기본값만 잰다.** 실행값은 `.env` 가 덮으므로 환경마다 다르고, 문서에 적으면 배포
환경마다 틀린다. AST 가 뽑는 것이 정확히 그 기본값이다.
"""

import ast
import importlib
import re
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_PATH = REPO_ROOT / "STATUS.md"
BACK_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BACK_DIR / "app" / "config.py"

# 문서가 마지막으로 사람 눈을 거친 커밋. 이후 app/ 이 이만큼 넘게 바뀌면 경고한다.
DRIFT_WARN_LINES = 300

# 상수 표의 한 행: | `항목` | `기본값` | `출처` | `env 키` |
# 값 칸만 백틱이 없을 수 있다(`8개`·`(계산값)`·`—`)이므로 백틱을 선택적으로 받는다.
ROW = re.compile(
    r"^\|\s*`(?P<name>[A-Za-z_][A-Za-z_0-9]*)`"
    r"\s*\|\s*`?(?P<value>[^|`]+?)`?"
    r"\s*\|\s*`(?P<module>[A-Za-z_][A-Za-z_0-9.]*)`"
    r"\s*\|\s*`?(?P<env>[^|`]+?)`?\s*\|\s*$"
)

# 표기 규칙 표(항목/뜻/대조 방법)와 헤더·구분선은 상수 행이 아니다.
NOT_A_ROW = re.compile(r"^\|\s*(항목|-+|:?-+:?)\s*\|")

COUNT = re.compile(r"^(\d+)개$")
SKIP = "(계산값)"
NO_ENV = "—"

# 서술 구역이 가리키는 코드 위치: `Back/...` 형태의 백틱 경로.
DOC_PATH = re.compile(r"`(Back/[^`\s]+)`")


def _status_text() -> str:
    assert STATUS_PATH.exists(), f"STATUS.md 가 없다: {STATUS_PATH}"
    return STATUS_PATH.read_text(encoding="utf-8")


def _rows() -> list[dict]:
    """상수 표의 모든 행. 형식이 깨진 행은 여기서 걸러지지 않고 따로 잡는다."""
    rows = []
    for lineno, line in enumerate(_status_text().splitlines(), start=1):
        match = ROW.match(line)
        if match:
            row = match.groupdict()
            row["lineno"] = lineno
            rows.append(row)
    return rows


def _config_defaults() -> dict[str, str]:
    """config.py 의 `NAME = ... os.environ.get("KEY", DEFAULT) ...` 에서 DEFAULT 를 뽑는다.

    **AST 로 읽는다.** import 하면 `.env` 가 적용된 실행값이 나오는데, 문서가 적는 것은
    기본값이다. 그리고 import 는 dotenv 가 파일을 읽게 만들어 CI 와 로컬의 결과가 갈린다.

    기본값이 리터럴이 아닐 수 있으므로(`str(500 * 1024)`) `ast.unparse` 로 표현식을
    그대로 문자열화한다. 리터럴이면 `repr` 을 써서 표기를 안정시킨다.
    """
    tree = ast.parse(CONFIG_PATH.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        for call in ast.walk(node.value):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "get"
                and len(call.args) == 2
            ):
                default = call.args[1]
                try:
                    found[target.id] = repr(ast.literal_eval(default))
                except ValueError:
                    found[target.id] = ast.unparse(default)
                break
    return found


def _config_env_keys() -> set[str]:
    """config.py 가 실제로 읽는 환경변수 이름."""
    tree = ast.parse(CONFIG_PATH.read_text(encoding="utf-8"))
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def _actual(row: dict):
    """문서가 가리키는 심볼의 실제 값. 없으면 AttributeError·ImportError 가 올라온다."""
    if row["module"] == "app.config":
        defaults = _config_defaults()
        if row["name"] not in defaults:
            raise AttributeError(
                f"config.py 에 `{row['name']} = os.environ.get(...)` 가 없다"
            )
        return defaults[row["name"]]
    return getattr(importlib.import_module(row["module"]), row["name"])


# ── 상수 표 ──────────────────────────────────────────────────

def test_status_md_has_constant_rows():
    """정규식이 아무것도 못 잡아도 아래 테스트는 전부 통과한다. 그 허위 통과를 막는다."""
    rows = _rows()
    assert len(rows) > 50, f"상수 행을 {len(rows)}개만 찾았다 — 표 형식이 바뀌었는가?"
    assert any(r["module"] == "app.config" for r in rows)
    assert any(r["module"] != "app.config" for r in rows)


def test_no_malformed_rows():
    """4열 표 안에 있는데 형식이 깨진 행. 조용히 검사에서 빠지는 것을 막는다."""
    lines = _status_text().splitlines()
    broken = []
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.count("|") != 5:
            continue
        if NOT_A_ROW.match(stripped) or ROW.match(stripped):
            continue
        broken.append(f"  {lineno}행: {stripped}")
    assert not broken, "상수 표에 형식이 깨진 행이 있다:\n" + "\n".join(broken)


def test_documented_symbols_exist():
    """STATUS.md 에 있는데 코드에 없는 심볼."""
    missing = []
    for row in _rows():
        try:
            _actual(row)
        except (AttributeError, ImportError) as e:
            missing.append(f"  {row['lineno']}행 {row['module']}.{row['name']}: {e}")
    assert not missing, "STATUS.md 에 있는데 코드에 없다:\n" + "\n".join(missing)


def test_documented_values_match_code():
    """문서의 값과 코드의 값이 같은가. 다르면 어느 항목이 어떻게 다른지 전부 출력한다."""
    mismatches = []
    for row in _rows():
        documented = row["value"].strip()
        if documented == SKIP:
            continue
        try:
            actual = _actual(row)
        except (AttributeError, ImportError):
            continue  # test_documented_symbols_exist 가 보고한다

        count = COUNT.match(documented)
        if count:
            if not hasattr(actual, "__len__"):
                mismatches.append(
                    f"  {row['lineno']}행 {row['module']}.{row['name']}:"
                    f" 문서는 `{documented}` 인데 코드 값은 길이가 없는 {type(actual).__name__}"
                )
            elif len(actual) != int(count.group(1)):
                mismatches.append(
                    f"  {row['lineno']}행 {row['module']}.{row['name']}:"
                    f" 문서 {documented} ≠ 코드 {len(actual)}개"
                )
            continue

        # app.config 는 이미 문자열(AST 표현), 나머지는 값이라 repr 로 맞춘다.
        actual_text = actual if row["module"] == "app.config" else repr(actual)
        if actual_text != documented:
            mismatches.append(
                f"  {row['lineno']}행 {row['module']}.{row['name']}:"
                f" 문서 `{documented}` ≠ 코드 `{actual_text}`"
            )

    assert not mismatches, (
        "STATUS.md 의 값이 코드와 다르다 (코드가 정답이다):\n" + "\n".join(mismatches)
    )


def test_env_keys_exist_in_config():
    """문서가 적어 둔 env 키가 config.py 에 실제로 있는가.

    `.env.example` 과의 대조는 test_config.py 가 한다. 여기는 STATUS.md 가 "이 값은
    env 로 덮을 수 있다"고 말한 것이 사실인지만 본다 — 거짓이면 읽는 사람이 없는
    설정을 `.env` 에 적고 왜 안 먹는지 헤매게 된다.
    """
    known = _config_env_keys()
    wrong = []
    for row in _rows():
        key = row["env"].strip()
        if key == NO_ENV:
            continue
        if key not in known:
            wrong.append(
                f"  {row['lineno']}행 {row['name']}: env 키 `{key}` 를 config.py 가 읽지 않는다"
            )
    assert not wrong, "STATUS.md 의 env 키가 config.py 에 없다:\n" + "\n".join(wrong)


def test_env_overridable_settings_declare_a_key():
    """config.py 의 설정 행은 env 키 칸을 비워 두면 안 된다."""
    blank = [
        f"  {row['lineno']}행 {row['name']}"
        for row in _rows()
        if row["module"] == "app.config" and row["env"].strip() == NO_ENV
    ]
    assert not blank, (
        "config.py 설정인데 env 키가 `—` 로 적혀 있다 (전부 덮을 수 있다):\n" + "\n".join(blank)
    )


# ── 서술 구역 ────────────────────────────────────────────────

def test_narrative_paths_exist():
    """서술 구역이 가리키는 코드 위치가 실재하는가.

    내용이 맞는지는 잴 수 없다. 하지만 **구조가 바뀌었는데 문서만 남은 상태**는 잡힌다 —
    파일이 사라지거나 이름이 바뀌면 여기서 깨진다.
    """
    referenced = sorted(set(DOC_PATH.findall(_status_text())))
    assert len(referenced) > 5, f"서술 구역에서 코드 경로를 {len(referenced)}개만 찾았다"
    missing = [p for p in referenced if not (REPO_ROOT / p).exists()]
    assert not missing, (
        "STATUS.md 가 가리키는 경로가 없다 (파일이 옮겨졌거나 지워졌다):\n"
        + "\n".join(f"  {p}" for p in missing)
    )


def test_narrative_is_not_too_stale():
    """'최종 확인' 커밋 이후 app/ 이 얼마나 바뀌었는지. **실패가 아니라 경고다.**

    서술은 자동으로 잴 수 없으므로, 대신 "문서를 한 번 볼 때가 됐다"는 신호만 낸다.
    실패로 만들면 코드를 고칠 때마다 무관한 테스트가 깨져 아무도 안 믿게 된다.
    """
    match = re.search(r"최종 확인:\s*([0-9a-f]{7,40})", _status_text())
    assert match, "STATUS.md 서술 구역에 '최종 확인: <커밋 해시>' 줄이 없다"
    commit = match.group(1)

    git = shutil.which("git")
    if git is None:
        pytest.skip(
            "git 이 PATH 에 없어 문서 낡음 검사를 건너뛴다"
            " — 환경 문제이지 STATUS.md 의 문제가 아니다."
            " 재려면 git 을 PATH 에 넣고 다시 실행할 것"
        )

    result = subprocess.run(
        [git, "diff", "--numstat", f"{commit}..HEAD", "--", "Back/app"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(
            f"'최종 확인' 커밋 {commit} 을 이 클론에서 찾을 수 없어 건너뛴다"
            " (얕은 클론이거나 리베이스됐다) — STATUS.md 의 문제가 아니다"
        )

    changed = sum(
        int(n)
        for line in result.stdout.splitlines()
        for n in line.split("\t")[:2]
        if n.isdigit()
    )
    if changed > DRIFT_WARN_LINES:
        warnings.warn(
            f"STATUS.md 가 낡았을 수 있다: '최종 확인' 커밋 {commit} 이후"
            f" Back/app/ 이 {changed}줄 바뀌었다 (경고 임계 {DRIFT_WARN_LINES}줄)."
            " STATUS.md §2 를 훑어 서술이 아직 맞는지 보고, 맞으면 '최종 확인' 해시를"
            " 지금 HEAD 로 올릴 것. **이것은 실패가 아니라 경고다** — 서술은 자동으로"
            " 잴 수 없어서 '볼 때가 됐다'는 신호만 낸다.",
            stacklevel=1,
        )
