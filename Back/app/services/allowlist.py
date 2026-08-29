"""분석을 허용할 저장소 목록. 공개 데모라 아무 저장소나 받으면 비용이 열려 있다.

`DAILY_TOKEN_LIMIT` 은 비용 천장이라 서비스 전체 합산이고, 한 명이 큰 저장소를
몇 개 넣으면 나머지가 막힌다. 무는 것은 LLM 비용만이 아니다 — 색인은 큐가 하나뿐이라
큰 저장소 하나가 그 뒤의 모든 색인을 세운다.

**로그인이 생겨도 이 목록은 따로 필요하다.** 로그인은 누가 썼는지를 알려줄 뿐
무엇을 분석할지는 안 가른다. 사용자별 상한(`USER_DAILY_LIMIT`)이 한 사람의 몫을
제한하기는 하지만, 그 몫으로 무엇을 색인할지는 여전히 이 목록이 정한다.

**목록은 코드가 아니라 배포 설정이 정한다**(`config.ALLOWED_REPOS`). 저장소 이름을
프로덕션 코드에 쓰지 않는다는 규칙(CLAUDE.md §7) 때문이기도 하고, 무엇을 데모로 걸지는
배포마다 다른 값이라 애초에 코드가 알 일이 아니다. 이 모듈이 아는 것은 형식뿐이다.

**비어 있으면 제한을 끈다.** 상한들이 `0` 으로 꺼지는 것과 같은 관용구다 — 로컬 개발은
`.env` 에 이 값을 안 적으면 지금까지처럼 임의 저장소를 넣을 수 있고, 켜는 곳은 배포의
`--env-file` 하나뿐이다. 끄는 스위치를 따로 만들지 않는 이유는 둘이 되면 어느 쪽이
이기는지를 또 기억해야 하기 때문이다.
"""

from app.config import ALLOWED_REPOS


class RepoNotAllowed(Exception):
    """허용 목록에 없는 저장소. status_code는 API 계층이 그대로 응답에 쓴다."""

    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


def _parse(raw: str) -> tuple[str, ...]:
    """`owner/name` 을 쉼표로 이은 문자열 → 정규화된 튜플. 순서는 적힌 대로 둔다.

    **소문자로 접는다.** `parse_github_url` 이 owner/repo 를 소문자로 돌려주므로
    설정 쪽에 대문자로 적혀 있으면 그대로는 영영 안 맞는다. GitHub 자체가 저장소
    이름의 대소문자를 구분하지 않아서, 적은 사람은 틀렸다는 것도 모른다.

    순서를 지키는 것은 차단 메시지에 그대로 실리기 때문이다 — 사람이 적은 차례가
    유지되는 편이 읽기 좋고, 정렬하면 설정과 화면이 다르게 보인다.
    """
    seen, items = set(), []
    for entry in raw.split(","):
        name = entry.strip().strip("/").lower()
        if name and name not in seen:
            seen.add(name)
            items.append(name)
    return tuple(items)


ALLOWED = _parse(ALLOWED_REPOS)


def enabled() -> bool:
    """목록이 비어 있으면 이 제한은 꺼진 상태다."""
    return bool(ALLOWED)


def check(owner: str, name: str) -> None:
    """허용 목록에 없으면 RepoNotAllowed. 꺼져 있으면 아무 일도 하지 않는다.

    **owner/name 은 `parse_github_url` 이 준 소문자 키를 그대로 받는다.** 여기서
    다시 정규화하지 않는 이유는, 하면 "무엇이 이미 정규화된 값인가"가 흐려져서
    호출부마다 다르게 접게 되기 때문이다.
    """
    if not ALLOWED or f"{owner}/{name}" in ALLOWED:
        return
    raise RepoNotAllowed(
        "이 서비스는 공개 데모라 지정된 저장소만 분석합니다. "
        f"사용할 수 있는 저장소: {', '.join(ALLOWED)}"
    )
