"""답변에서 인용(파일 + 행 범위)을 뽑는다.

**이 모듈이 유일한 인용 파서다.** 전에는 `tests/test_line_accuracy.py` 안에만 있었는데,
화면에서 인용을 클릭할 수 있게 하려면 프로덕션도 같은 것을 뽑아야 한다. 프론트에서
정규식을 새로 짜면 **"테스트가 채점하는 인용"과 "화면에 링크로 뜨는 인용"이 다른
집합**이 되고, 한쪽만 고치면 조용히 어긋난다.

**뽑기만 하고 판정하지 않는다.** "그 행 번호가 맞는가"는 `test_line_accuracy.py` 의
`_verdict()` 가 한다 — 화면은 코드를 보여줄 뿐이고 맞았는지는 사람이 본다.
실측 정확도가 72.4% 라서, **틀린 것을 감추지 않는 것이 이 기능의 목적이다.**

## 규칙의 한계 — 알고 쓴다

자연어를 정규식으로 뽑는 것이라:
- **코드를 그대로 인용한 것만 잡는다**(`CODE_LIKE`). 이름 하나만 적은 것은 "그 줄에 이
  문자열이 있다"는 주장이 아니라 서술이다
- 파일명이 그 줄에 없으면 **직전에 언급된 것**을 쓴다 — 답변이 파일을 제목으로 한 번
  쓰고 아래 불릿에 행 번호만 적는 형식이 흔하다
"""

import re

# "41~100행", "102-124행", "35행". 물결·붙임표·en dash 를 모두 받는다.
RANGE_RE = re.compile(r"(\d{1,5})\s*[~\-–]\s*(\d{1,5})\s*행")
SINGLE_RE = re.compile(r"(?<![\d~\-–])(\d{1,5})\s*행")
# 백틱 안의 내용. 파일명인지 코드인지는 뒤에서 가른다.
TICK_RE = re.compile(r"`([^`]+)`")

# 이보다 짧은 조각은 어디에나 있어 변별력이 없다(`size` 같은 것).
MIN_SNIPPET_CHARS = 6

# **코드를 그대로 인용한 것만 잡는다.** 공백이나 구두점이 있어야 한다.
#
# 왜: `ApnsChannel`·`String`·`IOException` 처럼 이름 하나만 적은 것은 "그 줄에 이 문자열이
# 있다"는 주장이 아니라 "이 범위가 이런 일을 한다"는 서술이다. 그걸 문자열 위치로 채점하면
# 모델이 아니라 **파서의 오탐**을 재게 된다.
CODE_LIKE = re.compile(r"[ ;={}]|\(\s*\w")

# 행 번호를 말하면서 범위를 크게 잡는 답변이 있다. 너무 넓으면 "맞다"가 무의미해진다.
MAX_RANGE_LINES = 200


def looks_like_path(text: str) -> bool:
    return "/" in text or bool(re.search(r"\.\w{1,4}$", text))


def resolve_path(name: str, paths: list[str]) -> str | None:
    """답변이 말한 경로를 실제 보관 경로로. 접미사로 맞춘다(답변은 경로를 줄여 쓴다).

    **둘 이상 맞으면 버린다.** `User.java` 가 여러 패키지에 있을 때 아무거나 고르면
    화면이 엉뚱한 파일을 열어 준다 — 링크가 없는 편이 낫다.

    `paths` 가 비면 언제나 None 이다. 그래서 **보관 소스가 없는 스냅샷에서는 인용이
    아예 안 만들어지고, 죽은 링크가 구조적으로 생기지 않는다.**
    """
    name = name.strip().lstrip("./")
    if not name:
        return None
    matches = [p for p in paths if p.endswith(name)]
    return matches[0] if len(matches) == 1 else None


def extract(answer: str) -> list[dict]:
    """답변에서 `(파일, 행범위, 코드조각들, 답변 안 위치)` 를 뽑는다.

    `marker` 는 답변에 **실제로 쓰인 글자**("26-91행")이고 `offset` 은 답변 문자열 안의
    그 시작 위치다. 화면이 이 둘로 링크를 건다 — `offset` 으로 렌더 트리의 노드를 고르고
    `marker` 로 노드 안 위치를 정한다(마크다운 렌더러가 줄 앞뒤 공백을 지워서 offset
    산술만으로는 어긋난다).

    줄 경계는 `splitlines()` 와 같다. offset 을 세려고 `split("\\n")` 으로 바꾸면
    CRLF 답변에서 줄이 `\\r` 로 끝나 기존 판정과 달라진다 — `keepends=True` 로 길이만
    누적하고 자르는 규칙은 그대로 둔다.
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
        if not current_file:
            offset += len(raw)
            continue

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

        snippets = [
            t for t in ticks
            if not looks_like_path(t)
            and len(t.strip()) >= MIN_SNIPPET_CHARS
            and CODE_LIKE.search(t)
        ]
        if not snippets:
            offset += len(raw)
            continue

        for start, end, match in spans:
            if start <= end and (end - start) <= MAX_RANGE_LINES:
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


def for_answer(answer: str, paths: list[str]) -> list[dict]:
    """화면에 줄 인용 목록. 실제 보관 경로로 해석되는 것만 남긴다.

    해석되지 않는 인용은 **버린다** — 링크를 만들어 놓고 404 를 띄우는 것보다
    링크가 없는 편이 낫다. `snippets` 는 판정용이라 여기서는 빼고 보낸다.
    """
    resolved = []
    for cite in extract(answer):
        path = resolve_path(cite["file"], paths)
        if path is None:
            continue
        resolved.append({
            "path": path,
            "start_line": cite["start"],
            "end_line": cite["end"],
            "marker": cite["marker"],
            "offset": cite["offset"],
        })
    return resolved
