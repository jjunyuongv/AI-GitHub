import pytest

from app.services import github_client
from app.services.github_client import (
    RepoAccessError,
    check_repo_access,
    list_public_repos,
    parse_github_url,
)

# 전부 같은 저장소를 가리키는 입력들. 정규화 후 ("facebook", "react")가 나와야 한다.
EQUIVALENT_URLS = [
    "https://github.com/facebook/react",
    "https://github.com/Facebook/React",
    "https://github.com/FACEBOOK/REACT",
    "https://github.com/facebook/react/",
    "https://github.com/facebook/react.git",
    "https://github.com/facebook/react.git/",
    "https://github.com/facebook/react/tree/main",
    "https://github.com/facebook/react/tree/main/packages/react-dom",
    "https://github.com/facebook/react/blob/main/README.md",
    "https://github.com/facebook/react/issues/123",
    "https://github.com/facebook/react?tab=readme-ov-file",
    "https://github.com/facebook/react#readme",
    "http://github.com/facebook/react",
    "https://www.github.com/facebook/react",
    "github.com/facebook/react",
    "https://GitHub.com/facebook/react",
    "  https://github.com/facebook/react  ",
]


@pytest.mark.parametrize("url", EQUIVALENT_URLS)
def test_normalizes_to_owner_repo(url):
    assert parse_github_url(url) == ("facebook", "react")


def test_all_variants_are_equal():
    """같은 레포를 다르게 입력해도 하나로 취급되는지 — 이 함수의 목적."""
    results = {parse_github_url(url) for url in EQUIVALENT_URLS}
    assert len(results) == 1


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/Bob/my-repo_v2.0", ("bob", "my-repo_v2.0")),
        ("https://github.com/A-Org/some.repo", ("a-org", "some.repo")),
    ],
)
def test_preserves_valid_name_characters(url, expected):
    """대소문자 말고는 이름을 건드리지 않는다."""
    assert parse_github_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "https://gitlab.com/facebook/react",
        "https://example.com/github.com/facebook/react",  # 호스트 위장
        "not a url",
        "https://github.com",
        "https://github.com/facebook",  # repo 없음
        "https://github.com/facebook/",
        "https://github.com/settings/profile",  # 예약 경로
        "https://github.com/Settings/profile",
        "https://github.com/marketplace/copilot",
        "https://github.com/facebook/re act",  # 이름에 공백
        "https://github.com/페이스북/리액트",
        "https://github.com/facebook/.git",  # .git 제거 후 빈 이름
    ],
)
def test_rejects_invalid_input(url):
    with pytest.raises(ValueError):
        parse_github_url(url)


def test_error_message_is_korean():
    with pytest.raises(ValueError, match="GitHub 저장소 URL이 아닙니다"):
        parse_github_url("https://gitlab.com/facebook/react")


# --- check_repo_access -------------------------------------------------------

REPO_PAYLOAD = {
    "owner": {"login": "Microsoft"},
    "name": "TypeScript",
    "default_branch": "main",
    "size": 2960340,
    "archived": False,
    "description": "TypeScript is a superset of JavaScript.",
    "language": "TypeScript",
    "stargazers_count": 110185,
}


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        return self._response


@pytest.fixture
def github_responds(monkeypatch):
    """GET /repos 응답을 위조한다. 실제 네트워크는 타지 않는다."""

    def _install(status_code, payload=None):
        response = _FakeResponse(status_code, payload if payload is not None else {})
        monkeypatch.setattr(
            github_client.httpx, "Client", lambda **kwargs: _FakeClient(response)
        )

    return _install


def test_returns_info_for_accessible_repo(github_responds):
    github_responds(200, REPO_PAYLOAD)

    info = check_repo_access("microsoft", "typescript")

    assert info["owner"] == "Microsoft"  # 소문자 키가 아니라 정식 표기
    assert info["name"] == "TypeScript"
    assert info["default_branch"] == "main"
    assert info["size_kb"] == 2960340
    assert info["archived"] is False


def test_reports_archived_repo(github_responds):
    github_responds(200, {**REPO_PAYLOAD, "archived": True})

    assert check_repo_access("o", "r")["archived"] is True


@pytest.mark.parametrize(
    "status_code, payload, expected_status, expected_message",
    [
        (404, None, 404, "찾을 수 없습니다"),
        (403, None, 429, "요청 한도를 초과"),
        (429, None, 429, "요청 한도를 초과"),
        (500, None, 502, "GitHub API 오류"),
        # 422는 FastAPI 본문 검증 전용으로 두고, 빈 저장소는 400으로 보낸다.
        (200, {**REPO_PAYLOAD, "size": 0}, 400, "비어 있어"),
    ],
)
def test_rejects_unusable_repo(
    github_responds, status_code, payload, expected_status, expected_message
):
    github_responds(status_code, payload)

    with pytest.raises(RepoAccessError, match=expected_message) as exc:
        check_repo_access("microsoft", "typescript")
    assert exc.value.status_code == expected_status


def test_size_limit_is_off_by_default(github_responds):
    """MAX_REPO_SIZE_KB 기본값 0 = 제한 없음. 2.9GB 레포도 통과한다."""
    github_responds(200, REPO_PAYLOAD)

    assert github_client.MAX_REPO_SIZE_KB == 0
    assert check_repo_access("microsoft", "typescript")["size_kb"] == 2960340


def test_size_limit_rejects_when_configured(github_responds, monkeypatch):
    github_responds(200, REPO_PAYLOAD)
    monkeypatch.setattr(github_client, "MAX_REPO_SIZE_KB", 500_000)

    with pytest.raises(RepoAccessError, match="너무 큽니다") as exc:
        check_repo_access("microsoft", "typescript")
    assert exc.value.status_code == 413


# --- list_public_repos -------------------------------------------------------
#
# 사용자 토큰 없이 서버 토큰으로 공개 엔드포인트를 부른다. 여기서 고정하는 것은
# "빈 저장소를 뺀다", "`too_large` 가 check_repo_access 와 같은 식이다", "최근 push 순 100개".


def _repo(name, size, **extra):
    return {
        "owner": {"login": "Octocat"},
        "name": name,
        "html_url": f"https://github.com/Octocat/{name}",
        "description": None,
        "language": "Python",
        "size": size,
        "pushed_at": "2026-08-30T00:00:00Z",
        "stargazers_count": 1,
        "fork": False,
        "archived": False,
        **extra,
    }


USER_PAYLOAD = {"login": "Octocat", "public_repos": 3}


class _FakeListClient:
    """GET 을 부른 순서대로 준비된 응답을 돌려주고, 부른 URL·파라미터를 남긴다."""

    def __init__(self, responses, calls):
        self._responses = list(responses)
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None, **kwargs):
        self._calls.append((url, params or {}))
        return self._responses.pop(0)


@pytest.fixture
def github_lists(monkeypatch):
    """GET /users/{login} 과 GET /users/{login}/repos 응답을 차례로 위조한다."""
    calls: list[tuple] = []

    def _install(user=(200, USER_PAYLOAD), repos=(200, [])):
        responses = [_FakeResponse(*user), _FakeResponse(*repos)]
        monkeypatch.setattr(
            github_client.httpx, "Client", lambda **kwargs: _FakeListClient(responses, calls)
        )
        return calls

    return _install


def test_list_skips_empty_repos_and_carries_flags(github_lists, monkeypatch):
    """**빈 저장소(size 0)는 목록에서 뺀다** — check_repo_access 가 400 으로 막으므로
    목록에 두면 눌러야 오류가 난다. 포크·보관은 거르지 않고 플래그만 싣는다.

    대역이 셋이라 거르기를 지우면 2개가 3개가 되어 깨진다.
    """
    monkeypatch.setattr(github_client, "MAX_REPO_SIZE_KB", 0)
    github_lists(repos=(200, [
        _repo("alive", 10, fork=True),
        _repo("empty", 0),
        _repo("old", 20, archived=True, description="d", language=None),
    ]))

    result = list_public_repos("octocat")

    assert result["login"] == "Octocat"  # 소문자 인자가 아니라 정식 표기
    assert result["total"] == 3          # 총 개수는 GitHub 이 준 값 그대로 (빈 것 포함)
    assert [r["name"] for r in result["repos"]] == ["alive", "old"]
    assert result["repos"][0] == {
        "owner": "Octocat",
        "name": "alive",
        "html_url": "https://github.com/Octocat/alive",
        "description": None,
        "language": "Python",
        "size_kb": 10,
        "pushed_at": "2026-08-30T00:00:00Z",
        "stars": 1,
        "fork": True,
        "archived": False,
        "too_large": False,
    }
    assert result["repos"][1]["archived"] is True


def test_too_large_uses_the_same_boundary_as_check_repo_access(github_lists, monkeypatch):
    """`MAX_REPO_SIZE_KB=1000` 에서 **1000 은 통과, 1001 은 초과**다.

    경계 양쪽을 다 둔다 — 한쪽만 있으면 `>` 를 `>=` 로 바꿔도 결과가 같아 변이가 통과한다.
    이 값은 check_repo_access 의 413 판정과 같은 식(`_too_large`)이라야 한다.
    """
    monkeypatch.setattr(github_client, "MAX_REPO_SIZE_KB", 1000)
    github_lists(repos=(200, [_repo("at-limit", 1000), _repo("over", 1001)]))

    flags = {r["name"]: r["too_large"] for r in list_public_repos("octocat")["repos"]}

    assert flags == {"at-limit": False, "over": True}


def test_too_large_is_off_when_limit_is_zero(github_lists, monkeypatch):
    """기본값 0 = 제한 없음. 위와 같은 대역이 둘 다 False 다."""
    monkeypatch.setattr(github_client, "MAX_REPO_SIZE_KB", 0)
    github_lists(repos=(200, [_repo("at-limit", 1000), _repo("over", 1001)]))

    flags = {r["name"]: r["too_large"] for r in list_public_repos("octocat")["repos"]}

    assert flags == {"at-limit": False, "over": False}


def test_list_asks_for_owned_repos_by_recent_push(github_lists):
    """요청 파라미터를 직접 본다 — 정렬을 지우면 응답 대역으로는 안 잡힌다."""
    calls = github_lists()

    list_public_repos("octocat")

    assert [url for url, _ in calls] == [
        f"{github_client.API_BASE}/users/octocat",
        f"{github_client.API_BASE}/users/octocat/repos",
    ]
    assert calls[1][1] == {
        "per_page": 100, "sort": "pushed", "direction": "desc", "type": "owner",
    }


@pytest.mark.parametrize(
    "status_code, expected_status, expected_message",
    [
        (404, 404, "찾을 수 없습니다"),
        (403, 429, "요청 한도를 초과"),
        (429, 429, "요청 한도를 초과"),
        (500, 502, "GitHub API 오류"),
    ],
)
def test_list_maps_github_errors(github_lists, status_code, expected_status, expected_message):
    calls = github_lists(user=(status_code, {}))

    with pytest.raises(RepoAccessError, match=expected_message) as exc:
        list_public_repos("octocat")

    assert exc.value.status_code == expected_status
    assert len(calls) == 1  # 프로필에서 막히면 목록은 부르지 않는다


def test_list_maps_errors_from_the_repos_call_too(github_lists):
    github_lists(repos=(500, {}))

    with pytest.raises(RepoAccessError) as exc:
        list_public_repos("octocat")

    assert exc.value.status_code == 502
