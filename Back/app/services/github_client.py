import base64
import re
import tarfile
import tempfile
from urllib.parse import urlsplit

import httpx

from app.config import (
    GITHUB_TOKEN,
    MAX_ARCHIVE_BYTES,
    MAX_REPO_SIZE_KB,
    MAX_SOURCE_FILE_BYTES,
    MAX_SOURCE_FILES,
)
from app.core.languages import language_for

API_BASE = "https://api.github.com"

MANIFEST_FILES = [
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "Gemfile",
    "composer.json",
]

MAX_TREE_ENTRIES = 200
MAX_FILE_CHARS = 3000

GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})

# github.com/settings 처럼 저장소가 아닌 페이지. owner 자리에 오면 저장소로 볼 수 없다.
RESERVED_OWNERS = frozenset({
    "settings", "marketplace", "explore", "topics", "trending", "collections",
    "events", "sponsors", "notifications", "new", "login", "logout", "join",
    "about", "pricing", "features", "security", "organizations", "orgs",
    "apps", "search", "pulls", "issues", "dashboard", "codespaces", "stars", "users",
})

NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class RepoAccessError(Exception):
    """분석할 수 없는 저장소. status_code는 API 계층이 그대로 응답에 쓴다."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def parse_github_url(url: str) -> tuple[str, str]:
    """GitHub URL에서 owner/repo를 소문자로 뽑아낸다.

    같은 저장소를 하나로 취급하기 위한 키다. 대소문자, 끝 슬래시, .git,
    tree/main 같은 뒤 경로, 쿼리스트링이 달라도 같은 값이 나온다.
    """
    url = url.strip()
    if not url:
        raise ValueError("URL이 비어 있습니다.")

    # 스킴이 없으면 urlsplit이 호스트를 경로로 읽어버린다.
    parts = urlsplit(url if "://" in url else f"https://{url}")
    if parts.hostname not in GITHUB_HOSTS:
        raise ValueError(f"GitHub 저장소 URL이 아닙니다: {url}")

    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < 2:
        raise ValueError(f"URL에 owner/repo 경로가 없습니다: {url}")

    # 3번째 이후 세그먼트(tree/main, issues/1 등)는 같은 저장소를 가리키므로 버린다.
    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]

    if not NAME_PATTERN.match(owner) or not NAME_PATTERN.match(repo) or repo in (".", ".."):
        raise ValueError(f"저장소 이름에 쓸 수 없는 문자가 있습니다: {owner}/{repo}")
    if owner.lower() in RESERVED_OWNERS:
        raise ValueError(f"GitHub 예약 경로라 저장소로 볼 수 없습니다: {owner}")

    return owner.lower(), repo.lower()


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _decode_content(payload: dict) -> str:
    if payload.get("encoding") == "base64":
        return base64.b64decode(payload["content"]).decode("utf-8", errors="replace")
    return payload.get("content", "")


def fetch_rate_limit() -> dict:
    """GitHub API 잔여 요청 수. 토큰이 없으면 core가 시간당 60으로 낮다."""
    with httpx.Client(headers=_headers(), timeout=10.0) as client:
        resp = client.get(f"{API_BASE}/rate_limit")
        resp.raise_for_status()
        resources = resp.json().get("resources", {})

    return {
        "authenticated": bool(GITHUB_TOKEN),
        "resources": [
            {"name": name, **resources[name]}
            for name in ("core", "search", "graphql")
            if name in resources
        ],
    }


def check_repo_access(owner: str, repo: str) -> dict:
    """LLM을 호출하기 전에 분석 가능한 저장소인지 확인하고 메타 정보를 돌려준다.

    비공개·삭제·빈 저장소를 여기서 걸러 LLM 호출까지 가지 않게 한다.
    반환값을 fetch_repo_context(access=...)로 넘기면 GET /repos 재호출을 피할 수 있다.
    """
    with httpx.Client(headers=_headers(), timeout=15.0, follow_redirects=True) as client:
        resp = client.get(f"{API_BASE}/repos/{owner}/{repo}")

    if resp.status_code == 404:
        raise RepoAccessError(
            f"{owner}/{repo} 저장소를 찾을 수 없습니다. 비공개 저장소이거나 존재하지 않는 주소입니다.",
            404,
        )
    if resp.status_code in (403, 429):
        raise RepoAccessError(
            "GitHub API 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.", 429
        )
    if resp.status_code != 200:
        raise RepoAccessError(
            f"GitHub API 오류 ({resp.status_code}). 잠시 후 다시 시도해 주세요.", 502
        )

    meta = resp.json()
    size_kb = meta.get("size", 0)
    if size_kb == 0:
        # 422는 FastAPI가 요청 본문 검증 실패에 쓰므로 겹치지 않게 400을 쓴다.
        raise RepoAccessError(f"{owner}/{repo} 는 비어 있어 분석할 내용이 없습니다.", 400)
    if MAX_REPO_SIZE_KB and size_kb > MAX_REPO_SIZE_KB:
        raise RepoAccessError(
            f"저장소가 너무 큽니다 ({size_kb // 1024}MB). "
            f"{MAX_REPO_SIZE_KB // 1024}MB 이하만 분석할 수 있습니다.",
            413,
        )

    return {
        # owner/repo 인자는 소문자 정규화 키라서 표시용 정식 표기를 따로 담는다.
        "owner": meta["owner"]["login"],
        "name": meta["name"],
        "default_branch": meta["default_branch"],
        "size_kb": size_kb,
        "archived": meta.get("archived", False),
        # 캐시 무효화 기준. 저장소가 갱신되면 이 값이 바뀐다.
        "pushed_at": meta.get("pushed_at", ""),
        "description": meta.get("description"),
        "primary_language": meta.get("language"),
        "stars": meta.get("stargazers_count", 0),
    }


def repo_meta(access: dict) -> dict:
    """check_repo_access() 결과에서 응답용 저장소 정보만 추린다."""
    return {
        key: access[key]
        for key in ("owner", "name", "description", "primary_language", "stars")
    }


def fetch_repo_context(owner: str, repo: str, access: dict | None = None) -> dict:
    """access를 넘기면 GET /repos를 건너뛴다. 없으면 여기서 직접 확인한다."""
    if access is None:
        access = check_repo_access(owner, repo)

    with httpx.Client(headers=_headers(), timeout=15.0, follow_redirects=True) as client:
        readme_resp = client.get(f"{API_BASE}/repos/{owner}/{repo}/readme")
        readme = _decode_content(readme_resp.json())[:MAX_FILE_CHARS] if readme_resp.status_code == 200 else ""

        branch = access["default_branch"]
        tree_resp = client.get(
            f"{API_BASE}/repos/{owner}/{repo}/git/trees/{branch}",
            params={"recursive": "1"},
        )
        tree_resp.raise_for_status()
        tree = tree_resp.json().get("tree", [])
        all_paths = [item["path"] for item in tree if item["type"] == "blob"]
        paths = all_paths[:MAX_TREE_ENTRIES]

        manifests = {}
        for path in all_paths:
            filename = path.rsplit("/", 1)[-1]
            if filename in MANIFEST_FILES and path.count("/") <= 1:
                content_resp = client.get(f"{API_BASE}/repos/{owner}/{repo}/contents/{path}")
                if content_resp.status_code == 200:
                    manifests[path] = _decode_content(content_resp.json())[:MAX_FILE_CHARS]

        return {
            "meta": repo_meta(access),
            "readme": readme,
            "file_paths": paths,
            "manifests": manifests,
        }


# 소스가 아닌 게 확실한 디렉터리. 의존성·빌드 산출물은 저장소의 코드가 아니라
# 검색 결과를 오염시키기만 한다 (node_modules 하나가 파일 수천 개다).
SKIP_DIR_PARTS = frozenset({
    "node_modules", "vendor", "dist", "build", "out", "target",
    ".git", ".venv", "venv", "__pycache__", ".next", ".nuxt",
    "site-packages", "bower_components", "third_party",
})
# migrations 는 일부러 뺐다 — 자동 생성이라 노이즈이긴 하지만
# "DB 스키마가 어떻게 생겼어?" 같은 질문의 유일한 근거일 때가 있다.


def _is_skippable(path: str) -> bool:
    """의존성·빌드 산출물이거나 생성된 파일이면 True."""
    parts = path.split("/")
    if SKIP_DIR_PARTS.intersection(parts):
        return True
    name = parts[-1]
    # 번들·압축 결과물은 한 줄에 수만 자라 청킹해도 의미가 없다.
    return ".min." in name or name.endswith((".lock", ".map"))


def fetch_source_files(owner: str, repo: str, ref: str = "") -> dict[str, str]:
    """저장소의 소스 파일 본문을 {경로: 내용} 으로 돌려준다.

    **tarball 한 번**으로 받는다. 파일마다 /contents 를 부르면 요청이 파일 수만큼
    늘어 rate limit 이 먼저 터지지만(레포당 수백 회), tarball 은 몇 MB 를 받는 대신
    GitHub 요청이 1회다.

    ref 를 비우면 GitHub 이 기본 브랜치를 쓴다 — 브랜치 이름을 알아내려고
    check_repo_access 를 한 번 더 부르지 않아도 된다.

    아카이브가 MAX_ARCHIVE_BYTES 를 넘으면 받다가 413 으로 끊는다 — 반쪽짜리
    인덱스를 만들지 않고 실패로 남긴다(호출부가 사유를 사용자에게 보여준다).
    """
    url = f"{API_BASE}/repos/{owner}/{repo}/tarball/{ref}" if ref else \
        f"{API_BASE}/repos/{owner}/{repo}/tarball"

    # 32MB 까지는 메모리, 넘으면 디스크로 넘어간다 — 저장소 하나가 수백 MB 일 수 있고
    # (3D 에셋·이미지가 든 저장소), 그걸 통째로 메모리에 올릴 이유가 없다.
    with tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024) as buffer:
        with httpx.Client(headers=_headers(), timeout=60.0, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code in (403, 429):
                    raise RepoAccessError(
                        "GitHub API 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.", 429
                    )
                if resp.status_code != 200:
                    raise RepoAccessError(
                        f"저장소 아카이브를 받지 못했습니다 ({resp.status_code}).", 502
                    )
                # 전부 받은 뒤 크기를 재면 이미 늦다. 받으면서 끊는다.
                for chunk in resp.iter_bytes():
                    buffer.write(chunk)
                    if MAX_ARCHIVE_BYTES and buffer.tell() > MAX_ARCHIVE_BYTES:
                        raise RepoAccessError(
                            f"저장소 아카이브가 너무 큽니다 "
                            f"({MAX_ARCHIVE_BYTES // (1024 * 1024)}MB 초과).",
                            413,
                        )

        buffer.seek(0)
        files: dict[str, str] = {}
        with tarfile.open(fileobj=buffer, mode="r:gz") as archive:
            for member in archive:
                if MAX_SOURCE_FILES and len(files) >= MAX_SOURCE_FILES:
                    break
                if not member.isfile():
                    continue
                if MAX_SOURCE_FILE_BYTES and member.size > MAX_SOURCE_FILE_BYTES:
                    continue

                # tarball 최상위는 {owner}-{repo}-{sha}/ 다. 저장소 기준 경로로 되돌린다.
                path = member.name.partition("/")[2]
                if not path or _is_skippable(path) or language_for(path) is None:
                    continue

                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                raw = extracted.read()
                # 확장자가 소스여도 실제로는 바이너리인 경우가 있다 (테스트 픽스처 등).
                if b"\x00" in raw:
                    continue
                files[path] = raw.decode("utf-8", errors="replace")

    return files
