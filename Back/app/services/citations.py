"""답변에서 인용(파일 + 행 범위)을 뽑는다.

**이 모듈이 유일한 인용 파서다.** 전에는 `tests/test_line_accuracy.py` 안에만 있었는데,
화면에서 인용을 클릭할 수 있게 하려면 프로덕션도 같은 것을 뽑아야 한다. 프론트에서
정규식을 새로 짜면 **"테스트가 채점하는 인용"과 "화면에 링크로 뜨는 인용"이 다른
집합**이 되고, 한쪽만 고치면 조용히 어긋난다.

**뽑기만 하고 판정하지 않는다.** "그 행 번호가 맞는가"는 `test_line_accuracy.py` 의
`_verdict()` 가 한다 — 화면은 코드를 보여줄 뿐이고 맞았는지는 사람이 본다.
실측 정확도가 72.4% 라서, **틀린 것을 감추지 않는 것이 이 기능의 목적이다.**

## 행 표기가 있으면 다 잡는다 — 채점 관문을 여기 두지 않는다

전에는 **같은 줄에 코드 조각이 있어야** 인용으로 쳤다(`CODE_LIKE`). 그 규칙은 채점의
오탐을 막으려는 것이었는데, 화면 경로까지 함께 막고 있었다 — 실측에서 파일명과 행
범위가 멀쩡히 잡힌 450건이 조각 하나 때문에 버려졌다. 화면은 조각이 필요 없다.
파일과 행 범위만 있으면 코드를 펼칠 수 있다.

그래서 **관문은 채점 쪽으로 옮겼다**(`tests/test_line_accuracy.py` 의 `CODE_LIKE`).
여기서는 `snippets` 를 **모아 두기만** 한다 — 채점이 쓸 재료이고, 이 모듈은 그것으로
무엇을 거르지 않는다.

## 규칙의 한계 — 알고 쓴다

자연어를 정규식으로 뽑는 것이라:
- 파일명이 그 줄에 없으면 **직전에 언급된 것**을 쓴다 — 답변이 파일을 제목으로 한 번
  쓰고 아래 불릿에 행 번호만 적는 형식이 흔하다
- 관문을 연 만큼 **오탐도 화면에 나온다.** 그것이 이 기능의 목적이다 — 사용자가 열어
  보고 닫으면 그만이고, 감추면 틀린 것을 고칠 수가 없다

## 버린 것은 센다

행 표기를 잡고도 인용을 못 만든 건수를 `dropped` 로 돌려준다. 전에는 이 수를 아는
경로가 없었다 — 프론트의 `onMiss` 는 **인용을 받은 뒤** 링크를 못 건 것만 세므로,
애초에 인용이 안 만들어진 유실은 어디에도 안 잡혔다.
"""

import logging
import re
from collections import Counter

# "41~100행", "102-124행", "35행". 물결·붙임표·en dash 를 모두 받는다.
RANGE_RE = re.compile(r"(\d{1,5})\s*[~\-–]\s*(\d{1,5})\s*행")
SINGLE_RE = re.compile(r"(?<![\d~\-–])(\d{1,5})\s*행")
# 백틱 안의 내용. 파일명인지 코드인지는 뒤에서 가른다.
TICK_RE = re.compile(r"`([^`]+)`")

# 채점이 쓸 조각의 하한. 이보다 짧으면 어디에나 있어 변별력이 없다(`size` 같은 것).
# **거르는 것은 `snippets` 목록이지 인용이 아니다** — 조각이 하나도 안 남아도 인용은 만든다.
MIN_SNIPPET_CHARS = 6

# 행 번호를 말하면서 범위를 크게 잡는 답변이 있다. 너무 넓으면 "맞다"가 무의미해진다.
MAX_RANGE_LINES = 200

logger = logging.getLogger(__name__)


def looks_like_path(text: str) -> bool:
    return "/" in text or bool(re.search(r"\.\w{1,4}$", text))


def _drop(dropped: Counter | None, reason: str, n: int = 1) -> None:
    """유실 사유를 센다. 세는 쪽이 없으면 아무 일도 하지 않는다."""
    if dropped is not None:
        dropped[reason] += n


def _matching_paths(name: str, paths: list[str]) -> list[str]:
    """접미사로 맞는 보관 경로 전부. 몇 개가 맞았는지로 유실 사유가 갈린다."""
    name = name.strip().lstrip("./")
    if not name:
        return []
    return [p for p in paths if p.endswith(name)]


def resolve_path(name: str, paths: list[str]) -> str | None:
    """답변이 말한 경로를 실제 보관 경로로. 접미사로 맞춘다(답변은 경로를 줄여 쓴다).

    **둘 이상 맞으면 버린다.** `User.java` 가 여러 패키지에 있을 때 아무거나 고르면
    화면이 엉뚱한 파일을 열어 준다 — 링크가 없는 편이 낫다.

    `paths` 가 비면 언제나 None 이다. 그래서 **보관 소스가 없는 스냅샷에서는 인용이
    아예 안 만들어지고, 죽은 링크가 구조적으로 생기지 않는다.**
    """
    matches = _matching_paths(name, paths)
    return matches[0] if len(matches) == 1 else None


def extract(answer: str, dropped: Counter | None = None) -> list[dict]:
    """답변에서 `(파일, 행범위, 코드조각들, 답변 안 위치)` 를 뽑는다.

    `marker` 는 답변에 **실제로 쓰인 글자**("26-91행")이고 `offset` 은 답변 문자열 안의
    그 시작 위치다. 화면이 이 둘로 링크를 건다 — `offset` 으로 렌더 트리의 노드를 고르고
    `marker` 로 노드 안 위치를 정한다(마크다운 렌더러가 줄 앞뒤 공백을 지워서 offset
    산술만으로는 어긋난다).

    `snippets` 는 **채점용 재료**다. 비어 있어도 인용은 만든다 — 화면은 조각이 필요 없다.

    줄 경계는 `splitlines()` 와 같다. offset 을 세려고 `split("\\n")` 으로 바꾸면
    CRLF 답변에서 줄이 `\\r` 로 끝나 기존 판정과 달라진다 — `keepends=True` 로 길이만
    누적하고 자르는 규칙은 그대로 둔다.

    `dropped` 를 주면 **행 표기를 잡고도 버린 건수**를 사유별로 담아 준다.
    """
    out: list[dict] = []
    current_file = None
    offset = 0

    for raw in answer.splitlines(keepends=True):
        stripped = raw.splitlines()
        line = stripped[0] if stripped else ""

        ticks = TICK_RE.findall(line)
        paths = [t for t in ticks if looks_like_path(t)]
        if paths:
            current_file = paths[-1]

        spans = [
            (int(m.group(1)), int(m.group(2)), m)
            for m in RANGE_RE.finditer(line)
        ]
        if not spans:
            spans = [
                (int(m.group(1)), int(m.group(1)), m)
                for m in SINGLE_RE.finditer(line)
            ]
        if not spans:
            offset += len(raw)
            continue

        # **행 표기를 잡은 뒤에 판다.** 앞에서 걸러 버리면 무엇을 잃었는지 셀 수 없다.
        if not current_file:
            _drop(dropped, "파일명 없음", len(spans))
            offset += len(raw)
            continue

        snippets = [
            t for t in ticks
            if not looks_like_path(t) and len(t.strip()) >= MIN_SNIPPET_CHARS
        ]

        for start, end, match in spans:
            if start > end:
                _drop(dropped, "범위가 뒤집힘")
                continue
            if (end - start) > MAX_RANGE_LINES:
                _drop(dropped, "범위가 너무 넓음")
                continue
            out.append({
                "file": current_file,
                "start": start,
                "end": end,
                "snippets": snippets,
                "marker": match.group(0),
                "offset": offset + match.start(),
            })
        offset += len(raw)

    return out


def for_answer(
    answer: str, paths: list[str], dropped: Counter | None = None
) -> list[dict]:
    """화면에 줄 인용 목록. 실제 보관 경로로 해석되는 것만 남긴다.

    해석되지 않는 인용은 **버린다** — 링크를 만들어 놓고 404 를 띄우는 것보다
    링크가 없는 편이 낫다. `snippets` 는 판정용이라 여기서는 빼고 보낸다.

    **행 범위가 파일 밖인지는 보지 않는다.** 여기서는 파일 내용을 모르기도 하고,
    무엇보다 그건 버릴 이유가 아니다 — 화면이 "이 파일은 N행뿐입니다"를 보여 준다.

    `dropped` 를 주면 `extract()` 의 유실과 여기서의 유실을 한 Counter 에 함께 담는다.
    """
    resolved = []
    for cite in extract(answer, dropped):
        matches = _matching_paths(cite["file"], paths)
        if len(matches) != 1:
            _drop(dropped, "접미사 중복" if matches else "경로 해석 실패")
            continue
        resolved.append({
            "path": matches[0],
            "start_line": cite["start"],
            "end_line": cite["end"],
            "marker": cite["marker"],
            "offset": cite["offset"],
        })
    return resolved
