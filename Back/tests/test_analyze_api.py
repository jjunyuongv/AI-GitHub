"""/analyze 가 대화 세션을 붙이는 부분만 확인한다.

GitHub·Claude·DB 를 전부 가짜로 바꾼다 (과금 없음, DB 없이 돈다).
Stage 1 의 실패 경로(400/404/429 등)는 이미 확인돼 있어 여기서 다시 다루지 않는다.
"""

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api import analyze as analyze_api
from app.main import app
from app.services import rate_limit, run_log, summary_cache

ACCESS = {
    "owner": "React",
    "name": "React",
    "default_branch": "main",
    "size_kb": 100,
    "archived": False,
    "pushed_at": "2026-08-14T09:12:33Z",
    "description": "웹 UI 라이브러리",
    "primary_language": "JavaScript",
    "stars": 1000,
}

SNAPSHOT = {
    "id": 42,
    "context": "## 레포지토리 정보\n- 이름: React/React",
    "summary": "요약 본문",
    "model": "claude-sonnet-5",
    "key_source": "pushed_at",
    "version": "20260814091233",
}


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    # 상한과 기록을 **파일 경로로 고정**한다. 개발 환경에는 DATABASE_URL 이 있어서
    # 그대로 두면 이 테스트가 실제 DB 의 카운터와 실행 기록을 건드린다.
    monkeypatch.setattr(rate_limit, "_use_db", lambda: False)
    monkeypatch.setattr(run_log.pool, "DATABASE_URL", "")
    monkeypatch.setattr(rate_limit, "STATE_PATH", tmp_path / "rate_limit.json")
    monkeypatch.setattr(run_log, "LOG_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rate_limit, "IP_RATE_LIMIT", 0)  # 이 파일에서는 제한을 끈다
    monkeypatch.setattr(rate_limit, "DAILY_LLM_CALL_LIMIT", 0)
    monkeypatch.setattr(rate_limit, "DAILY_TOKEN_LIMIT", 0)


@pytest.fixture(autouse=True)
def fake_github(monkeypatch):
    monkeypatch.setattr(analyze_api, "check_repo_access", lambda owner, repo: dict(ACCESS))
    # **소스 수집도 반드시 막는다.** 정적분석이 붙으면서 /analyze 가 tarball 을 받게
    # 됐는데, 이걸 안 막으면 테스트가 실제로 GitHub 에 요청한다 (실제로 그렇게 돌아
    # 전체 실행이 14초 → 25초가 됐다). 느려질 뿐 아니라 오프라인에서 깨지고 한도를 깎는다.
    monkeypatch.setattr(
        analyze_api, "fetch_source_files", lambda owner, repo, ref="": {"a.py": "x = 1\n"}
    )
    monkeypatch.setattr(
        analyze_api,
        "fetch_repo_context",
        lambda owner, repo, access=None: {
            "meta": {
                "owner": "React",
                "name": "React",
                "description": "웹 UI 라이브러리",
                "primary_language": "JavaScript",
                "stars": 1000,
            },
            "readme": "",
            "file_paths": [],
            "manifests": {},
        },
    )


@pytest.fixture
def llm_calls(monkeypatch):
    calls = []

    def fake_run_summary(context):
        calls.append(context)
        return {
            "text": "요약 본문",
            "llm_ms": 3000,
            "input_tokens": 2000,
            "output_tokens": 500,
            "cache_write_tokens": 5000,
            "cache_read_tokens": 0,
            "cost_usd": 0.009,
        }

    monkeypatch.setattr(analyze_api, "run_summary", fake_run_summary)
    return calls


@pytest.fixture
def sessions(monkeypatch):
    """세션 생성·조회를 기록하는 chats 대역.

    `existing` 에 담긴 세션만 조회에 걸린다. 재사용 여부를 확인하려면 조회가
    실제로 일어났는지도 봐야 해서 looked_up 을 함께 남긴다.
    """

    class FakeChats:
        def __init__(self):
            self.created: list[int] = []
            self.looked_up: list[str] = []
            self.existing: dict[str, dict] = {}

        def create_session(self, snapshot_id):
            self.created.append(snapshot_id)
            return f"session-for-{snapshot_id}"

        def get_session(self, session_id):
            self.looked_up.append(session_id)
            return self.existing.get(session_id)

    fake = FakeChats()
    monkeypatch.setattr(analyze_api, "chats", fake)
    return fake


@pytest.fixture
def client():
    # lifespan 은 돌리지 않는다 (init_schema 가 실제 DB 를 찾는다).
    return TestClient(app)


def _analyze(client, session_id=None):
    body = {"github_url": "https://github.com/facebook/react"}
    if session_id is not None:
        body["session_id"] = session_id
    return client.post("/analyze", json=body)


# --- 세션 재사용 -------------------------------------------------------------
#
# 이 인자가 없을 때는 분석마다 새 세션이 생겼고, 프론트가 localStorage 의 옛 세션을
# 복원하면 방금 만든 세션이 **메시지 없이** 남았다. 그 누적을 없애는 것이 목적이다.

EXISTING = "3f0d8f6e-1b2c-4d5e-8a9b-0c1d2e3f4a5b"


def test_existing_session_on_same_snapshot_is_reused(client, llm_calls, sessions, monkeypatch):
    """같은 스냅샷을 보고 있으면 새로 만들지 않는다 — 빈 세션이 쌓이던 원인이다."""
    monkeypatch.setattr(summary_cache, "get", lambda access: dict(SNAPSHOT))
    sessions.existing[EXISTING] = {"id": EXISTING, "snapshot_id": 42}

    res = _analyze(client, EXISTING)

    assert res.json()["session_id"] == EXISTING
    assert sessions.created == [], "이어 쓸 수 있는데 새 세션을 만들었다"
    assert sessions.looked_up == [EXISTING]


def test_session_on_a_different_snapshot_is_not_reused(client, llm_calls, sessions, monkeypatch):
    """스냅샷이 다르면 그 세션은 **옛 코드**를 보고 있다. 이어 쓰면 안 된다."""
    monkeypatch.setattr(summary_cache, "get", lambda access: dict(SNAPSHOT))
    sessions.existing[EXISTING] = {"id": EXISTING, "snapshot_id": 41}  # 옛 스냅샷

    res = _analyze(client, EXISTING)

    assert res.json()["session_id"] == "session-for-42"
    assert sessions.created == [42]


def test_unknown_session_falls_back_to_a_new_one(client, llm_calls, sessions, monkeypatch):
    """이미 정리된 세션 id 를 보내도 분석은 성공해야 한다."""
    monkeypatch.setattr(summary_cache, "get", lambda access: dict(SNAPSHOT))

    res = _analyze(client, EXISTING)

    assert res.status_code == 200
    assert res.json()["session_id"] == "session-for-42"
    assert sessions.created == [42]


def test_malformed_session_id_never_reaches_the_db(client, llm_calls, sessions, monkeypatch):
    """UUID 가 아닌 값을 DB 에 넘기면 형식 오류로 세션 생성 자체가 실패한다.

    /chat 은 같은 상황에서 400 을 내지만 여기서는 무시하고 새로 만든다 —
    이 값은 거들 뿐이라 분석이 그것 때문에 실패하면 안 된다.
    """
    monkeypatch.setattr(summary_cache, "get", lambda access: dict(SNAPSHOT))

    res = _analyze(client, "not-a-uuid")

    assert res.status_code == 200
    assert res.json()["session_id"] == "session-for-42"
    assert sessions.looked_up == [], "형식이 틀린 id 로 DB 를 조회했다"


def test_reuse_also_works_on_a_cache_miss(client, llm_calls, sessions, monkeypatch):
    """캐시 히트 경로에서만 고치면 절반만 고친 것이다 — 미스에서도 재사용해야 한다."""
    monkeypatch.setattr(summary_cache, "get", lambda access: None)
    monkeypatch.setattr(summary_cache, "put", lambda access, **kwargs: dict(SNAPSHOT))
    sessions.existing[EXISTING] = {"id": EXISTING, "snapshot_id": 42}

    res = _analyze(client, EXISTING)

    assert res.json()["session_id"] == EXISTING
    assert sessions.created == []


# --- 캐시 미스 ---------------------------------------------------------------


def test_miss_saves_context_and_starts_a_session(client, llm_calls, sessions, monkeypatch):
    saved = {}

    monkeypatch.setattr(summary_cache, "get", lambda access: None)
    monkeypatch.setattr(
        summary_cache,
        "put",
        lambda access, *, model, summary, context: saved.update(
            model=model, summary=summary, context=context
        )
        or dict(SNAPSHOT),
    )

    res = _analyze(client)

    assert res.status_code == 200
    assert res.json()["session_id"] == "session-for-42"
    assert len(llm_calls) == 1
    # 후속 질문이 재사용할 컨텍스트가 스냅샷에 함께 저장된다.
    assert saved["context"] == llm_calls[0]
    assert sessions.created == [42]


# --- 정적분석 ---------------------------------------------------------------


def test_analysis_reaches_the_summary_prompt(client, llm_calls, sessions, monkeypatch):
    """린터 집계가 요약 프롬프트에 들어가야 한다. 안 들어가면 요약이 상태를 말할 수 없다."""
    monkeypatch.setattr(summary_cache, "get", lambda access: None)
    monkeypatch.setattr(summary_cache, "put", lambda access, **kwargs: dict(SNAPSHOT))
    monkeypatch.setattr(
        analyze_api.static_analysis, "analyze",
        lambda files: [{
            "tool": "ruff", "language": "python", "rules_selected": "E9,F",
            "files_checked": 3, "total": 7,
            "top_rules": [{"code": "F401", "count": 7, "message": "imported but unused"}],
            "top_files": [{"path": "a.py", "count": 7}],
        }],
    )

    _analyze(client)

    assert "## 정적분석" in llm_calls[0]
    assert "F401" in llm_calls[0]


def test_analysis_failure_does_not_block_the_summary(client, llm_calls, sessions, monkeypatch):
    """**부가 기능의 실패가 본 기능을 막지 않는다.** 소스를 못 받아도 요약은 나와야 한다."""
    monkeypatch.setattr(summary_cache, "get", lambda access: None)
    monkeypatch.setattr(summary_cache, "put", lambda access, **kwargs: dict(SNAPSHOT))

    def boom(owner, repo, ref=""):
        raise RuntimeError("tarball 413")

    monkeypatch.setattr(analyze_api, "fetch_source_files", boom)

    res = _analyze(client)

    assert res.status_code == 200
    assert res.json()["summary"] == "요약 본문"
    assert "## 정적분석" not in llm_calls[0]


def test_fetched_sources_are_handed_to_indexing(client, llm_calls, sessions, monkeypatch):
    """**정적분석용으로 받은 소스를 색인에 넘긴다.**

    버리면 새 스냅샷마다 tarball 을 두 번 받는다 — 아카이브 다운로드는 core 와
    별개 제한을 받는다.
    """
    handed = {}
    monkeypatch.setattr(summary_cache, "get", lambda access: None)
    monkeypatch.setattr(summary_cache, "put", lambda access, **kwargs: dict(SNAPSHOT))
    monkeypatch.setattr(
        analyze_api.indexer, "start",
        lambda sid, owner, repo, files=None, **kw: handed.update(files=files),
    )

    _analyze(client)

    assert handed["files"] == {"a.py": "x = 1\n"}, "받은 소스를 색인에 넘기지 않았다"


def test_cache_hit_hands_nothing_to_indexing(client, llm_calls, sessions, monkeypatch):
    """캐시 히트는 소스를 받지 않으므로 넘길 것도 없다 — 색인이 스스로 받아야 한다."""
    handed = {}
    monkeypatch.setattr(summary_cache, "get", lambda access: dict(SNAPSHOT))
    monkeypatch.setattr(
        analyze_api.indexer, "start",
        lambda sid, owner, repo, files=None, **kw: handed.update(files=files),
    )

    _analyze(client)

    assert handed["files"] is None


def test_cache_hit_does_not_download_sources(client, llm_calls, sessions, monkeypatch):
    """**캐시 히트는 GitHub 도 LLM 도 더 부르지 않는다.**

    tarball 은 core 와 별개 제한을 받는다. 히트에 받으면 재분석마다 그 한도를 깎는다.
    """
    downloads = []
    monkeypatch.setattr(summary_cache, "get", lambda access: dict(SNAPSHOT))
    monkeypatch.setattr(
        analyze_api, "fetch_source_files",
        lambda owner, repo, ref="": downloads.append(repo) or {},
    )

    _analyze(client)

    assert downloads == [], "캐시 히트인데 tarball 을 받았다"


# --- 캐시 히트 ---------------------------------------------------------------


def test_hit_starts_a_session_without_calling_the_llm(client, llm_calls, sessions, monkeypatch):
    monkeypatch.setattr(summary_cache, "get", lambda access: dict(SNAPSHOT))

    res = _analyze(client)

    assert res.status_code == 200
    body = res.json()
    assert body["summary"] == "요약 본문"
    assert body["session_id"] == "session-for-42"
    assert llm_calls == []
    assert sessions.created == [42]


def test_hit_is_logged_as_a_cache_hit(client, llm_calls, sessions, monkeypatch):
    monkeypatch.setattr(summary_cache, "get", lambda access: dict(SNAPSHOT))

    _analyze(client)

    record = run_log.read(1)[0]
    assert record["cached"] is True
    assert record["source"] == "analyze"
    assert record["input_tokens"] == 0


# --- DB 를 못 쓸 때 ----------------------------------------------------------


def test_summary_survives_a_dead_database(client, llm_calls, monkeypatch):
    """DB 가 죽어도 요약은 돌려준다. 대화만 시작할 수 없다."""
    monkeypatch.setattr(summary_cache, "get", lambda access: None)
    monkeypatch.setattr(summary_cache, "put", lambda access, **kwargs: None)

    res = _analyze(client)

    assert res.status_code == 200
    assert res.json()["summary"] == "요약 본문"
    assert res.json()["session_id"] is None


def test_session_failure_does_not_break_the_response(client, llm_calls, monkeypatch):
    monkeypatch.setattr(summary_cache, "get", lambda access: None)
    monkeypatch.setattr(summary_cache, "put", lambda access, **kwargs: dict(SNAPSHOT))

    class DeadChats:
        def create_session(self, snapshot_id):
            raise psycopg.OperationalError("연결 실패")

    monkeypatch.setattr(analyze_api, "chats", DeadChats())

    res = _analyze(client)

    assert res.status_code == 200
    assert res.json()["session_id"] is None
