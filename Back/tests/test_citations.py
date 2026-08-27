"""인용 추출기. LLM·DB·네트워크를 쓰지 않는다 (순수 정규식).

**이 모듈이 유일한 파서라는 것이 이 테스트의 전제다.** `test_line_accuracy.py` 가 같은
`extract()` 로 행 번호 정확도를 채점하고, `/chat` 이 같은 것으로 화면 링크를 만든다.
규칙이 바뀌면 `-m evaluation tests/test_line_accuracy.py` 의 수치가 움직인다.
"""

from collections import Counter

from app.services.citations import (
    MIN_SNIPPET_CHARS,
    extract,
    for_answer,
    looks_like_path,
    resolve_path,
)

PATHS = [
    "src/main/java/com/pj/springboot/SecurityConfig.java",
    "src/main/java/com/pj/springboot/jpa/UserController.java",
    "src/main/java/com/pj/springboot/jpa/UserService.java",
]


# --- offset — 화면이 링크를 거는 자리 -----------------------------------------


def _points_at_marker(answer: str, cite: dict) -> bool:
    start = cite["offset"]
    return answer[start : start + len(cite["marker"])] == cite["marker"]


def test_offset_points_at_the_marker_in_the_answer():
    """**offset 이 원문을 정확히 가리켜야 한다.** 어긋나면 화면이 엉뚱한 글자에 링크를 건다."""
    answer = (
        "비밀번호는 BCrypt 로 암호화합니다.\n"
        "\n"
        "- `SecurityConfig.java`(35-42행)에서 `return new BCryptPasswordEncoder()` 로 만듭니다.\n"
        "- `UserService.java`(26-49행)에서 `passwordEncoder.encode(raw)` 를 부릅니다.\n"
    )

    cites = extract(answer)

    assert len(cites) == 2
    assert all(_points_at_marker(answer, c) for c in cites)
    assert [c["marker"] for c in cites] == ["35-42행", "26-49행"]


def test_offsets_are_correct_across_many_lines():
    """줄이 쌓일수록 offset 누적이 어긋나기 쉽다. 긴 답변으로 확인한다."""
    body = "\n".join(
        f"- `UserService.java`({n}-{n + 5}행)에서 `doThing(x) {{}}` 를 부릅니다."
        for n in range(10, 200, 10)
    )
    answer = "설명 문단입니다.\n\n" + body + "\n"

    cites = extract(answer)

    assert len(cites) == 19
    assert all(_points_at_marker(answer, c) for c in cites)


def test_offsets_survive_crlf():
    """CRLF 답변에서도 offset 이 맞아야 한다 — 줄바꿈이 2바이트다."""
    answer = (
        "설명입니다.\r\n"
        "\r\n"
        "- `SecurityConfig.java`(35-42행)에서 `return new BCryptPasswordEncoder()` 를 씁니다.\r\n"
    )

    cites = extract(answer)

    assert len(cites) == 1
    assert _points_at_marker(answer, cites[0])


# --- 행 번호 표기 세 형태 ------------------------------------------------------


def test_range_with_tilde_hyphen_and_endash():
    for marker, expected in (("41~100행", (41, 100)), ("102-124행", (102, 124))):
        answer = f"- `UserService.java`({marker}) 에서 `save(user) {{}}` 를 부릅니다."

        cite = extract(answer)[0]

        assert (cite["start"], cite["end"]) == expected
        assert cite["marker"] == marker


def test_single_line_becomes_a_one_line_range():
    answer = "- `UserService.java` 35행의 `this.size = (n > m)` 를 보세요."

    cite = extract(answer)[0]

    assert (cite["start"], cite["end"]) == (35, 35)
    assert cite["marker"] == "35행"


def test_a_range_wins_over_single_numbers_on_the_same_line():
    """범위가 있으면 그것만 쓴다 — 같은 줄의 숫자를 또 단일 행으로 세면 중복된다."""
    answer = "- `UserService.java`(26-49행)에서 `encode(raw) {}` 를 부릅니다."

    assert len(extract(answer)) == 1


# --- 파일명이 직전 줄에서 이어진다 --------------------------------------------


def test_the_file_carries_over_from_an_earlier_line():
    """답변이 파일을 제목으로 한 번 쓰고 아래 불릿에 행 번호만 적는 형식이 흔하다."""
    answer = (
        "## `SecurityConfig.java`\n"
        "\n"
        "- 35-42행에서 `return new BCryptPasswordEncoder()` 로 만듭니다.\n"
        "- 62-77행에서 `http.authorizeHttpRequests(auth -> auth)` 를 설정합니다.\n"
    )

    cites = extract(answer)

    assert [c["file"] for c in cites] == ["SecurityConfig.java"] * 2
    assert [c["start"] for c in cites] == [35, 62]
    assert all(_points_at_marker(answer, c) for c in cites)


def test_a_line_number_before_any_file_is_dropped():
    """어느 파일인지 모르는 행 번호는 링크를 걸 곳이 없다."""
    answer = "35-42행에서 `PasswordEncoder` 빈을 만듭니다."

    assert extract(answer) == []


# --- 행 표기가 있으면 다 잡는다 ------------------------------------------------


def test_a_bare_name_in_backticks_is_still_a_citation():
    """`PasswordEncoder` 처럼 이름 하나만 적어도 **인용은 만든다.**

    전에는 여기서 버렸다. 그 규칙(`CODE_LIKE`)은 채점의 오탐을 막으려던 것인데 화면
    경로까지 막고 있었다 — 지금은 `tests/test_line_accuracy.py` 로 옮겼다.
    """
    answer = "- `UserService.java`(26-49행)에서 `PasswordEncoder` 를 씁니다."

    cites = extract(answer)

    assert len(cites) == 1
    assert (cites[0]["start"], cites[0]["end"]) == (26, 49)


def test_a_line_with_no_backticks_at_all_is_still_a_citation():
    """실제로 링크가 안 되던 모양이다 — 파일명은 앞 줄에서 잇고 조각은 아예 없다."""
    answer = (
        "## `ChatHandler.java`\n"
        "\n"
        "- 연결이 끊기면 29~32행에서 세션을 지웁니다.\n"
    )

    cites = extract(answer)

    assert len(cites) == 1
    assert cites[0]["marker"] == "29~32행"
    assert cites[0]["snippets"] == []


def test_a_short_snippet_is_not_kept_for_scoring():
    """`size` 같은 짧은 조각은 어디에나 있어 변별력이 없다 — **채점 재료에서** 뺀다.

    **조각을 `MIN_SNIPPET_CHARS` 경계에 딱 맞춘다.** `a=b`(3자)처럼 한참 짧은 것을 쓰면
    상한을 4로 낮추는 변이가 통과한다 — 실제로 그랬다. 5자짜리 코드 모양 조각이라야
    "6이면 버리고 5면 남긴다"가 갈린다.

    관문이 옮겨진 뒤로는 **인용 자체는 만들어진다.** 갈리는 것은 `snippets` 뿐이다.
    """
    short = "a = b"                      # 5자
    assert len(short) == MIN_SNIPPET_CHARS - 1

    answer = f"- `UserService.java`(26-49행)에서 `{short}` 를 씁니다."

    assert extract(answer)[0]["snippets"] == []


def test_a_snippet_exactly_at_the_minimum_is_kept():
    """경계의 반대쪽. 이게 없으면 상한을 올리는 변이가 안 잡힌다."""
    exact = "a == b"                     # 6자
    assert len(exact) == MIN_SNIPPET_CHARS

    answer = f"- `UserService.java`(26-49행)에서 `{exact}` 를 씁니다."

    assert extract(answer)[0]["snippets"] == [exact]


def test_an_absurdly_wide_range_is_dropped():
    """범위가 너무 넓으면 "맞다"가 무의미해진다."""
    answer = "- `UserService.java`(1-9999행)에서 `save(user) {}` 를 부릅니다."

    assert extract(answer) == []


# --- 경로 해석 ----------------------------------------------------------------


def test_a_suffix_resolves_to_the_stored_path():
    assert resolve_path("SecurityConfig.java", PATHS) == PATHS[0]
    assert resolve_path("jpa/UserService.java", PATHS) == PATHS[2]


def test_an_ambiguous_suffix_resolves_to_nothing():
    """같은 이름이 여러 패키지에 있으면 아무거나 고르면 안 된다 — 엉뚱한 파일이 열린다."""
    dupes = ["a/User.java", "b/User.java"]

    assert resolve_path("User.java", dupes) is None


def test_a_leading_dot_slash_is_stripped():
    assert resolve_path("./SecurityConfig.java", PATHS) == PATHS[0]


def test_an_unknown_path_resolves_to_nothing():
    assert resolve_path("Nope.java", PATHS) is None


# --- for_answer — 화면에 주는 목록 --------------------------------------------


ANSWER = (
    "비밀번호는 BCrypt 로 암호화합니다.\n"
    "- `SecurityConfig.java`(35-42행)에서 `return new BCryptPasswordEncoder()` 로 만듭니다.\n"
    "- `Nope.java`(1-5행)에서 `doThing(x) {}` 를 부릅니다.\n"
)


def test_for_answer_resolves_and_drops_the_unresolvable():
    """**링크를 만들어 놓고 404 를 띄우는 것보다 링크가 없는 편이 낫다.**"""
    cites = for_answer(ANSWER, PATHS)

    assert len(cites) == 1
    assert cites[0]["path"] == PATHS[0]
    assert (cites[0]["start_line"], cites[0]["end_line"]) == (35, 42)
    assert cites[0]["marker"] == "35-42행"


def test_no_stored_paths_means_no_citations():
    """보관 소스가 없는 스냅샷에서 죽은 링크가 **구조적으로** 안 생기는 근거다.

    특례 처리가 아니라 경로 해석이 보관 목록에 기대는 설계의 결과다.
    """
    assert for_answer(ANSWER, []) == []


def test_for_answer_drops_the_judging_only_field():
    """`snippets` 는 채점용이다. 화면에 보낼 이유가 없다."""
    assert "snippets" not in for_answer(ANSWER, PATHS)[0]


def test_an_answer_without_citations_gives_an_empty_list():
    assert for_answer("주어진 정보로는 알 수 없습니다.", PATHS) == []


# --- 버린 것을 센다 ------------------------------------------------------------


def test_dropped_counts_each_reason_separately():
    """사유가 뭉뚱그려지면 무엇을 고쳐야 하는지 알 수 없다.

    세 사유가 **서로 다른 칸에** 들어가는지 본다 — 한 칸에 몰아넣는 변이가 통과하면
    안 된다. 그래서 건수도 사유마다 다르게 만든다(경로 해석 실패만 2건).
    """
    answer = (
        "35-42행에서 `save(user) {}` 를 부릅니다.\n"                    # 파일명 없음
        "- `Nope.java`(1-5행)에서 `doThing(x) {}` 를 부릅니다.\n"        # 경로 해석 실패
        "- `Gone.java`(7-9행)에서 `doOther(x) {}` 를 부릅니다.\n"        # 경로 해석 실패
        "- `UserService.java`(1-9999행)에서 `save(u) {}` 를 부릅니다.\n"  # 너무 넓음
    )
    dropped = Counter()

    assert for_answer(answer, PATHS, dropped) == []
    assert dropped == Counter({
        "경로 해석 실패": 2,
        "파일명 없음": 1,
        "범위가 너무 넓음": 1,
    })


def test_an_ambiguous_suffix_is_counted_apart_from_an_unknown_one():
    """둘 다 `resolve_path` 는 None 이지만 **고칠 방법이 다르다.**

    중복은 답변이 경로를 더 길게 쓰면 풀리고, 해석 실패는 보관이 없거나 오타다.
    같은 칸에 세면 그 구분이 사라진다.
    """
    dupes = ["a/User.java", "b/User.java"]
    answer = "- `User.java`(1-5행)에서 `doThing(x) {}` 를 부릅니다."
    dropped = Counter()

    assert for_answer(answer, dupes, dropped) == []
    assert dropped == Counter({"접미사 중복": 1})


def test_nothing_is_counted_when_every_citation_resolves():
    dropped = Counter()

    for_answer("- `UserService.java`(26-49행)에서 `encode(raw) {}` 를 씁니다.", PATHS, dropped)

    assert dropped == Counter()


def test_an_out_of_file_range_is_not_a_drop():
    """**파일 밖은 버릴 이유가 아니다.** 화면이 "이 파일은 N행뿐입니다"를 보여 준다.

    여기서 버리면 틀린 인용이 조용히 사라져 이 기능의 목적과 반대가 된다.
    """
    dropped = Counter()

    cites = for_answer(
        "- `UserService.java` 99999행의 `encode(raw) {}` 를 보세요.", PATHS, dropped
    )

    assert [c["start_line"] for c in cites] == [99999]
    assert dropped == Counter()


# --- 파일명을 고르는 규칙 세 가지 ---------------------------------------------
#
# **셋을 따로 조인다.** 실측에서 기여도가 크게 갈렸기 때문이다 — 조이기 +136건,
# 풀리는 것 우선 **+1건**, 평문 +135건. 한 대역으로 뭉쳐 두면 +1 짜리 규칙을
# 통째로 지우는 변이가 조용히 통과한다.


def test_a_route_no_longer_hijacks_the_filename():
    """규칙 1 — `looks_like_path` 조이기.

    실측 유실 171건이 **전부** 이것이었다. 라우트·주석·산술식·점 표기가 파일명
    자리에 들어앉고, `current_file` 이 이어지는 성질 때문에 **다음 줄까지 오염된다.**

    **규칙 2 가 구제할 수 없는 모양이라야 이 규칙만 갈린다.** 그래서 라우트를 그 줄의
    **유일한** 후보로 둔다 — 풀리는 후보가 하나도 없으니 "풀리는 것 우선"은 할 일이 없다.
    옛 규칙(`"/" 포함`)이면 `/login` 이 `current_file` 이 되어 앞 줄의 파일을 덮고
    인용이 0건이다. 조인 규칙이면 후보 자체가 없어 앞 파일이 그대로 이어진다.

    실측 데모에서 정확히 이 모양으로 세 줄이 연달아 오염됐다(`/myChatServer`).
    """
    answer = (
        "## `SecurityConfig.java`\n"
        "\n"
        "- 35-42행에서 `/login` 으로 리다이렉트합니다.\n"
    )

    cites = for_answer(answer, PATHS)

    assert [c["path"] for c in cites] == [PATHS[0]]
    assert [c["start_line"] for c in cites] == [35]


def test_only_collected_extensions_count_as_a_path():
    """규칙 1의 경계 — 확장자 표가 판정 기준이다.

    `.java` 는 수집되고 `.gif` 는 안 된다. **양쪽을 다 둔다** — 한쪽만 있으면
    "확장자 표를 본다"를 "점이 있으면 통과"로 되돌리는 변이가 안 잡힌다.
    `np.isin` 은 실측에서 8건 잡아먹은 점 표기다.
    """
    assert looks_like_path("UserService.java")
    assert looks_like_path("src/main/java/com/pj/springboot/UserService.java")

    assert not looks_like_path("paging4.gif")          # 수집 대상이 아니다
    assert not looks_like_path("np.isin")              # 점 표기
    assert not looks_like_path("/login")               # 라우트
    assert not looks_like_path("src/main/java/jpa/")   # 디렉터리
    assert not looks_like_path("// trust all servers")  # 주석
    assert not looks_like_path("success / total * 100")  # 산술식


def test_a_resolvable_name_wins_over_a_later_unresolvable_one():
    """규칙 2 — 풀리는 것 우선.

    **둘 다 `.java` 라 규칙 1로는 안 갈린다.** 앞의 것만 보관돼 있고 뒤의 것은 없다.
    옛 규칙(`마지막 후보`)이면 뒤엣것이 이겨 "경로 해석 실패"가 되고, 새 규칙이면
    앞엣것으로 링크된다. 실측 기여는 +1건이지만 **규칙이 하는 일은 이것 하나다.**
    """
    answer = (
        "- **`UserService.java`의 `save()`** (26-49행): "
        "`LegacyUserService.java` 를 대신합니다.\n"
    )
    dropped = Counter()

    cites = for_answer(answer, PATHS, dropped)

    assert [c["path"] for c in cites] == [PATHS[2]]
    assert dropped == Counter()


def test_a_filename_outside_backticks_is_read():
    """규칙 3 — 백틱 밖 평문도 본다. 실측 +135건.

    모델이 파일명을 괄호 안 평문으로 적는 모양이 흔하다. **한글이 바로 붙어도**
    잘라내야 한다 — 토큰 정규식이 `\\w` 면 `UserService.java에서` 가 통째로 잡혀
    확장자 판정이 깨진다.
    """
    answer = "`save()` 는 (src/main/java/com/pj/springboot/jpa/UserService.java, 26-49행)에 있습니다.\n"

    cites = for_answer(answer, PATHS)

    assert [c["path"] for c in cites] == [PATHS[2]]

    korean_hugging = "`save()` 는 UserService.java에서 26-49행입니다.\n"

    assert [c["path"] for c in for_answer(korean_hugging, PATHS)] == [PATHS[2]]


def test_plain_text_is_only_trusted_when_it_resolves():
    """규칙 3의 반대쪽 — **평문은 풀릴 때만 받는다.**

    평문은 후보가 훨씬 많아 오탐이 여기서 난다. 풀리지 않는 평문 파일명은 무시하고
    **직전 줄의 파일이 그대로 이어져야 한다.** 이 대역이 없으면 "평문을 무조건
    후보로 받는다"는 변이가 통과하고, 그러면 인용이 엉뚱한 곳으로 붙거나 사라진다.
    """
    answer = (
        "## `UserService.java`\n"
        "\n"
        "- 26-49행은 LegacyUserService.java 와 같은 일을 합니다.\n"
    )

    cites = for_answer(answer, PATHS)

    assert [c["path"] for c in cites] == [PATHS[2]]


def test_an_unresolvable_backtick_name_still_becomes_the_current_file():
    """지목한 파일을 우리가 안 가졌으면 **유실로 세지, 직전 파일로 잇지 않는다.**

    이으면 엉뚱한 파일에 링크가 걸린다 — 링크가 없는 편이 낫다는 원칙의 연장이다.
    """
    answer = (
        "## `UserService.java`\n"
        "\n"
        "- `NotCollected.java`(1-5행)에서 `doThing(x) {}` 를 부릅니다.\n"
    )
    dropped = Counter()

    assert for_answer(answer, PATHS, dropped) == []
    assert dropped == Counter({"경로 해석 실패": 1})


def test_without_stored_paths_the_old_rule_still_applies():
    """`extract()` 는 보관 목록 **없이도** 돌아야 한다 — 채점 하네스의 단위 테스트가 그렇게 쓴다.

    목록이 없으면 풀리는지 알 수 없으므로 백틱 안 마지막 후보를 쓴다(옛 규칙).
    """
    answer = "- `SecurityConfig.java` 와 `UserService.java`(26-49행)를 봅니다.\n"

    assert [c["file"] for c in extract(answer)] == ["UserService.java"]
