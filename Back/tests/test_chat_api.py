"""POST /chat · GET /chat/{id} 경로 테스트.

DB 와 Claude 를 둘 다 가짜로 바꿔서 DB 없이, 과금 없이 돈다.
DB 쿼리 자체는 tests/test_db_chats.py 가 실제 PostgreSQL 로 확인한다.
"""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.main import app
from app.services import rate_limit, run_log

SESSION_ID = "11111111-2222-3333-4444-555555555555"

SESSION = {
    "id": SESSION_ID,
    "snapshot_id": 1,
    "context": "## 레포지토리 정보\n- 이름: React/React",
    "summary": "요약 본문",
    "model": "claude-sonnet-5",
    # owner/name 은 소문자 정규화 키(코드 인덱싱이 GitHub 을 부를 때 쓴다),
    # display_* 는 화면 표기다. 실제 chats.get_session() 이 둘 다 돌려준다.
    "owner": "react",
    "name": "react",
    "display_owner": "React",
    "display_name": "React",
    "created_at": "2026-08-15T00:00:00+00:00",
    "last_message_at": None,
}


class FakeChats:
    """chats 모듈 대역. 저장된 메시지를 리스트로 들고 있는다."""

    def __init__(self, session=SESSION):
        self.session = session
        self.messages: list[dict] = []
        self.history_limit = None

    def get_session(self, session_id):
        return self.session if session_id == SESSION_ID else None

    def list_messages(self, session_id, limit=None):
        self.history_limit = limit
        rows = [
            {"id": i, "created_at": "2026-08-15T00:00:00+00:00", **m}
            for i, m in enumerate(self.messages, start=1)
        ]
        return rows if limit is None else rows[-limit:]

    def add_exchange(self, session_id, question, answer):
        self.messages += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]


@pytest.fixture
def fake_chats(monkeypatch):
    chats = FakeChats()
    monkeypatch.setattr(chat_api, "chats", chats)
    return chats


class FakeIndexer:
    """indexer 모듈 대역.

    실제 indexer 는 GitHub tarball 을 받고 임베딩 모델을 돌린다 — 테스트가 네트워크와
    수백 MB 모델에 묶이면 안 되므로 통째로 갈아끼운다.
    인덱싱 자체는 tests/test_indexer.py 가 확인한다.
    """

    def __init__(self, snippets: str = "", ready: bool = True):
        self.snippets = snippets
        self.ready = ready
        self.started: list[tuple] = []
        self.searched: list[str] = []

    def is_ready(self, snapshot_id, table=None):
        return self.ready

    def start(self, snapshot_id, owner, repo, ref="", table=None):
        self.started.append((snapshot_id, owner, repo))
        return True

    def search_code(self, snapshot_id, question, limit=8):
        self.searched.append(question)
        return [{"path": "a.py"}] if self.snippets else []

    def format_snippets(self, found):
        return self.snippets if found else ""


@pytest.fixture(autouse=True)
def fake_indexer(monkeypatch):
    """기본은 '색인 완료, 검색 결과 없음'. 필요한 테스트만 따로 갈아끼운다."""
    fake = FakeIndexer()
    monkeypatch.setattr(chat_api, "indexer", fake)
    return fake


@pytest.fixture
def captured_call(monkeypatch):
    """run_chat 을 가로채 인자를 기록한다. 실제 LLM 호출은 하지 않는다."""
    calls = []

    def fake_run_chat(
        *, context, summary, history, question, snippets="", source_bundle=""
    ):
        calls.append({
            "context": context, "summary": summary, "history": history,
            "question": question, "snippets": snippets,
            "source_bundle": source_bundle,
        })
        return {
            "text": "가짜 답변",
            "llm_ms": 1200,
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_write_tokens": 0,
            "cache_read_tokens": 900,
            "cost_usd": 0.0007,
        }

    monkeypatch.setattr(chat_api, "run_chat", fake_run_chat)
    return calls


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    """남용 제한 상태와 실행 기록을 임시 **파일**로 돌린다.

    개발 환경에는 DATABASE_URL 이 있어서 끄지 않으면 코드가 DB 를 먼저 쓰고,
    그러면 이 테스트가 실제 카운터를 소모한다(IP 상한 테스트가 특히 그렇다).
    """
    monkeypatch.setattr(rate_limit, "_use_db", lambda: False)
    monkeypatch.setattr(run_log.pool, "DATABASE_URL", "")
    monkeypatch.setattr(rate_limit, "STATE_PATH", tmp_path / "rate_limit.json")
    monkeypatch.setattr(run_log, "LOG_PATH", tmp_path / "runs.jsonl")
    monkeypatch.setattr(rate_limit, "IP_RATE_LIMIT", 3)
    monkeypatch.setattr(rate_limit, "DAILY_LLM_CALL_LIMIT", 100)
    monkeypatch.setattr(rate_limit, "DAILY_TOKEN_LIMIT", 1_000_000)


@pytest.fixture
def client():
    # lifespan 을 돌리지 않는다 — init_schema 가 실제 DB 를 찾으려 든다.
    return TestClient(app)


def _ask(client, message="인증은 어디서 처리해?", session_id=SESSION_ID):
    return client.post("/chat", json={"session_id": session_id, "message": message})


# --- 정상 왕복 ---------------------------------------------------------------


def test_answer_is_returned_and_saved(client, fake_chats, captured_call):
    res = _ask(client)

    assert res.status_code == 200
    assert res.json() == {"session_id": SESSION_ID, "answer": "가짜 답변"}
    assert [(m["role"], m["content"]) for m in fake_chats.messages] == [
        ("user", "인증은 어디서 처리해?"),
        ("assistant", "가짜 답변"),
    ]


def test_code_is_searched_before_answering(
    client, fake_chats, captured_call, fake_indexer, monkeypatch
):
    """대화가 '추정'이 아니라 실제 코드로 답하려면, 검색이 LLM 호출 전에 끝나 있어야 한다."""
    monkeypatch.setattr(fake_indexer, "snippets", "## 질문과 관련된 코드\n```java\n@Bean\n```")

    _ask(client, "로그인 관련 부분은 어디에 있어?")

    assert fake_indexer.searched == ["로그인 관련 부분은 어디에 있어?"]
    assert "@Bean" in captured_call[0]["snippets"]


def test_unfinished_index_is_not_searched(
    client, fake_chats, captured_call, fake_indexer, monkeypatch
):
    """색인이 끝나기 전에는 검색하지 않는다.

    부분 인덱스로 검색하면 아직 임베딩하지 않은 코드가 '저장소에 없는 코드'처럼 보여
    틀린 답을 만든다. 대신 그 자리에서 색인을 시작시킨다(세션만 복원해 들어온 경우).
    """
    monkeypatch.setattr(fake_indexer, "ready", False)
    monkeypatch.setattr(fake_indexer, "snippets", "쓰이면 안 되는 코드")

    res = _ask(client)

    assert res.status_code == 200
    assert fake_indexer.searched == []
    assert captured_call[0]["snippets"] == ""
    # 색인은 세션이 보는 스냅샷과 정규화된 owner/name 으로 시작돼야 한다
    assert fake_indexer.started == [(1, "react", "react")]


def test_indexing_failure_does_not_block_the_answer(
    client, fake_chats, captured_call, monkeypatch
):
    """색인은 답변 품질을 올리는 부가 기능이다. 실패했다고 질문이 막히면 안 된다."""

    class BrokenIndexer:
        def is_ready(self, *a, **kw):
            raise RuntimeError("DB 다운")

        def start(self, *a, **kw):
            raise RuntimeError("DB 다운")

        def search_code(self, *a, **kw):
            return []

        def format_snippets(self, found):
            return ""

    monkeypatch.setattr(chat_api, "indexer", BrokenIndexer())

    res = _ask(client)

    assert res.status_code == 200
    assert res.json()["answer"] == "가짜 답변"
    # 코드 없이도 답은 나가야 하고, 그 경우 스니펫은 비어 있어야 한다
    assert captured_call[0]["snippets"] == ""


def test_snapshot_context_is_reused(client, fake_chats, captured_call):
    """후속 질문은 GitHub 을 다시 읽지 않고 저장된 스냅샷을 쓴다."""
    _ask(client)

    assert captured_call[0]["context"] == SESSION["context"]
    assert captured_call[0]["summary"] == "요약 본문"


def test_history_is_capped(client, fake_chats, captured_call):
    _ask(client)
    _ask(client, "두 번째 질문")

    assert fake_chats.history_limit == chat_api.MAX_HISTORY_MESSAGES
    # 두 번째 호출에는 첫 왕복이 이력으로 들어간다.
    assert [m["content"] for m in captured_call[1]["history"]] == [
        "인증은 어디서 처리해?",
        "가짜 답변",
    ]


def test_run_is_logged_as_chat(client, fake_chats, captured_call):
    _ask(client)

    record = run_log.read(1)[0]
    assert record["source"] == "chat"
    assert record["repo"] == "react/react"
    assert record["cached"] is False
    assert record["input_tokens"] == 100


# --- 실패 경로 ---------------------------------------------------------------


def test_unknown_session_is_404(client, fake_chats, captured_call):
    res = _ask(client, session_id="99999999-9999-9999-9999-999999999999")

    assert res.status_code == 404
    assert not captured_call  # LLM 은 부르지 않는다


def test_malformed_session_id_is_400(client, fake_chats, captured_call):
    res = _ask(client, session_id="not-a-uuid")

    assert res.status_code == 400
    assert not captured_call


def test_empty_message_is_400(client, fake_chats, captured_call):
    res = _ask(client, message="   ")

    assert res.status_code == 400
    assert not captured_call


def test_missing_field_is_422(client, fake_chats):
    """FastAPI 본문 검증 전용 코드. 우리 코드가 쓰는 400과 겹치지 않는다."""
    assert client.post("/chat", json={"session_id": SESSION_ID}).status_code == 422


def test_database_failure_is_503(client, monkeypatch, captured_call):
    class DeadChats(FakeChats):
        def get_session(self, session_id):
            raise psycopg.OperationalError("연결 실패")

    monkeypatch.setattr(chat_api, "chats", DeadChats())

    res = _ask(client)

    assert res.status_code == 503
    assert not captured_call


def test_ip_limit_is_enforced(client, fake_chats, captured_call):
    for _ in range(3):
        assert _ask(client).status_code == 200

    res = _ask(client)

    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) > 0
    assert len(captured_call) == 3


def test_save_failure_still_returns_the_answer(client, monkeypatch, captured_call):
    """토큰은 이미 썼다. 기록을 잃는 편이 답변을 잃는 것보다 낫다."""

    class HalfDeadChats(FakeChats):
        def add_exchange(self, session_id, question, answer):
            raise psycopg.OperationalError("쓰기 실패")

    monkeypatch.setattr(chat_api, "chats", HalfDeadChats())

    res = _ask(client)

    assert res.status_code == 200
    assert res.json()["answer"] == "가짜 답변"


# --- 이력 조회 ---------------------------------------------------------------


def test_history_returns_repo_and_messages(client, fake_chats, captured_call):
    _ask(client)

    res = client.get(f"/chat/{SESSION_ID}")

    assert res.status_code == 200
    body = res.json()
    assert body["repo"] == {"owner": "React", "name": "React"}
    assert body["summary"] == "요약 본문"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]


def test_history_of_unknown_session_is_404(client, fake_chats):
    assert client.get("/chat/99999999-9999-9999-9999-999999999999").status_code == 404


def test_history_does_not_consume_the_ip_limit(client, fake_chats, captured_call):
    for _ in range(5):
        assert client.get(f"/chat/{SESSION_ID}").status_code == 200

    # 제한(3)을 넘게 조회했어도 질문은 아직 가능하다.
    assert _ask(client).status_code == 200


# --- 색인 진행 상황 -----------------------------------------------------------


def _fake_status(monkeypatch, row):
    monkeypatch.setattr(chat_api.index_status, "get", lambda snapshot_id, table=None: row)


def test_index_status_reports_progress(client, fake_chats, monkeypatch):
    """진행률은 청크 수 기준이고, 남은 시간은 지금까지의 실제 속도로 계산한다."""
    _fake_status(monkeypatch, {
        "status": "running",
        "chunks_total": 1000,
        "chunks_done": 200,
        "error": None,
        # 200개에 100초 걸렸으니 남은 800개는 400초.
        "started_at": datetime.now(timezone.utc) - timedelta(seconds=100),
    })

    body = client.get(f"/chat/{SESSION_ID}/index").json()

    assert body["status"] == "running"
    assert (body["chunks_done"], body["chunks_total"]) == (200, 1000)
    assert 390 <= body["eta_seconds"] <= 410


def test_index_status_without_progress_has_no_eta(client, fake_chats, monkeypatch):
    """아직 한 개도 못 끝냈으면 속도를 모른다. 지어내지 않는다."""
    _fake_status(monkeypatch, {
        "status": "running",
        "chunks_total": 0,
        "chunks_done": 0,
        "error": None,
        "started_at": datetime.now(timezone.utc),
    })

    assert client.get(f"/chat/{SESSION_ID}/index").json()["eta_seconds"] is None


def test_index_status_reports_failure_reason(client, fake_chats, monkeypatch):
    """실패는 '진행 중'과 구분돼야 하고, 사유가 화면까지 가야 한다."""
    _fake_status(monkeypatch, {
        "status": "failed",
        "chunks_total": 0,
        "chunks_done": 0,
        "error": "저장소 아카이브가 너무 큽니다 (500MB 초과).",
        "started_at": datetime.now(timezone.utc),
    })

    body = client.get(f"/chat/{SESSION_ID}/index").json()

    assert body["status"] == "failed"
    assert "500MB" in body["error"]
    assert body["eta_seconds"] is None


def test_index_status_is_pending_when_not_started(client, fake_chats, monkeypatch):
    _fake_status(monkeypatch, None)

    assert client.get(f"/chat/{SESSION_ID}/index").json()["status"] == "pending"


def test_index_status_of_unknown_session_is_404(client, fake_chats):
    res = client.get("/chat/99999999-9999-9999-9999-999999999999/index")

    assert res.status_code == 404
