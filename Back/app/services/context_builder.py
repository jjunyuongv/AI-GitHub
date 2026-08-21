from app.core.languages import language_for

# 문자 → 토큰 보수적 환산율. count_tokens 가 실패했을 때만 쓴다.
#
# 실측(대화 로그)에서 한국어 비중이 높은 컨텍스트가 9,964자 → 약 5,000토큰으로
# 2.0자/토큰이었다. 코드는 보통 3자/토큰대라 이 값을 쓰면 토큰을 실제보다 많게
# 잡는다 — **틀리더라도 우회를 덜 켜는 쪽으로 틀려야** 비용이 새지 않는다.
CHARS_PER_TOKEN = 2.0


def build_context(ctx: dict, analysis: list[dict] | None = None) -> str:
    meta = ctx["meta"]
    sections = [
        "## 레포지토리 정보",
        f"- 이름: {meta['owner']}/{meta['name']}",
        f"- 설명: {meta['description'] or '(없음)'}",
        f"- 주 언어: {meta['primary_language'] or '(불명)'}",
        f"- 스타: {meta['stars']}",
    ]

    if ctx["readme"]:
        sections += ["", "## README", ctx["readme"]]

    for path, content in ctx["manifests"].items():
        sections += ["", f"## {path}", content]

    sections += ["", "## 파일 목록", "\n".join(ctx["file_paths"])]

    if analysis:
        sections += ["", build_analysis_section(analysis)]

    return "\n".join(sections)


def build_analysis_section(analysis: list[dict]) -> str:
    """정적분석 집계를 프롬프트에 넣을 블록으로.

    **경고를 한 건씩 넣지 않는다.** 큰 저장소는 수천 건이라 프롬프트가 그것으로 찬다.
    무엇이 얼마나 많은지와 어디에 몰려 있는지면 요약이 상태를 말하기에 충분하다.

    **검사한 언어와 규칙을 함께 적는다.** 이걸 빼면 파이썬이 없어 결과가 없는 저장소와
    깨끗한 저장소를 모델이 구분하지 못해서, "정적분석 결과 문제가 없습니다" 같은
    근거 없는 문장을 쓰게 된다.
    """
    lines = ["## 정적분석"]
    for result in analysis:
        lines.append(
            f"- {result['tool']}({result['language']}, 규칙 {result['rules_selected']})"
            f": {result['files_checked']}개 파일 검사 · 경고 {result['total']}건"
        )
        for rule in result["top_rules"]:
            lines.append(f"  - {rule['code']} {rule['count']}건 — {rule['message']}")
        if result["top_files"]:
            dense = " · ".join(
                f"{f['path']} {f['count']}건" for f in result["top_files"]
            )
            lines.append(f"  - 경고가 몰린 파일: {dense}")
    lines.append("- 검사하지 않은 언어의 코드에 대해서는 아무것도 알 수 없습니다.")
    return "\n".join(lines)


def number_lines(text: str, start: int = 1) -> str:
    """`12|코드` 형식으로 줄 번호를 붙인다.

    전체 주입(번들)과 RAG(스니펫)이 **같은 형식**을 써야 한다. 달랐을 때 실제로 문제가
    됐다 — 스니펫에는 번호가 없는데 시스템 프롬프트가 "줄 번호가 붙어 있다"고 말해서,
    모델이 없는 번호를 참조하려다 조금씩 어긋난 행을 짚었다(오프셋 +3 ~ +22).

    start 는 그 텍스트의 첫 줄이 원본에서 몇 번째인가다. 청크는 파일 중간에서 잘려 나오므로
    1 부터 세면 안 된다.
    """
    return "\n".join(
        f"{n}|{line}" for n, line in enumerate(text.splitlines(), start=start)
    )


def build_source_bundle(files: dict[str, str]) -> str:
    """저장소 소스 전체를 프롬프트에 넣을 한 덩어리로. 작은 저장소의 RAG 우회용.

    **줄 번호를 붙인다.** CHAT_SYSTEM_PROMPT 가 "어느 파일 몇 행인지 밝히세요"를
    요구하는데, 번호 없이 주면 모델이 세어서 지어낸다 — 틀린 근거는 근거가 없는 것보다
    나쁘다. RAG 경로의 format_snippets() 도 같은 이유로 행 범위를 붙인다.

    번호 표기는 `12|코드` 다. 자리를 맞추거나(`   12| `) 뒤에 공백을 두면 읽기는 좋아지지만
    **읽는 쪽이 모델이라 그 정렬은 값이 없고 토큰만 든다** — 실측에서 5자리 정렬이 번호 없는
    번들 대비 +26.0%, 이 표기는 +15.8% 였다 (Java 저장소, 3,959줄 기준 5,531토큰 차이).

    경로 순으로 정렬한다. 딕셔너리 순서(tarball 순서)에 맡기면 같은 저장소도 실행마다
    바이트가 달라질 수 있는데, 이 문자열은 캐시 접두사가 되므로 그러면 캐시가 매번 깨진다.
    """
    if not files:
        return ""

    blocks = ["## 저장소 전체 소스"]
    for path in sorted(files):
        numbered = number_lines(files[path])
        blocks.append(
            f"\n### {path}\n```{language_for(path) or ''}\n{numbered}\n```"
        )
    return "\n".join(blocks)


def estimate_tokens(text: str) -> int:
    """문자 수 기반 토큰 추정. count_tokens 가 실패했을 때의 대체값."""
    return round(len(text) / CHARS_PER_TOKEN)
