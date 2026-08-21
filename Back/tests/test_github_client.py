import pytest

from app.services import github_client
from app.services.github_client import RepoAccessError, check_repo_access, parse_github_url

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
