"""저정보 청크 감점 규칙. DB 도 임베딩 모델도 쓰지 않는다 (순수 판정·정렬 로직)."""

import pytest

from app.services import indexer


def _chunk(content: str, language: str = "java") -> dict:
    return {
        "path": f"src/A.{language}",
        "language": language,
        "start_line": 1,
        "end_line": 10,
        "content": content,
        "distance": 0.1,
    }


# ── 감점 대상 ────────────────────────────────────────────────

def test_stylesheets_are_low_info():
    """CSS 는 한국어 주석이 많아 한국어 질의와 곧잘 맞지만 '어떻게 동작하는가'의 답은 아니다.

    실측에서 ko_03·ko_05·ko_08 의 상위 절반을 CSS 가 차지했다.
    """
    css = _chunk("/* 페이지네이션 링크 스타일 */\n.paging a { color: #333; }", language="css")
    assert indexer.is_low_info(css) is True


def test_entry_points_are_low_info():
    """어느 저장소에나 있고 내용이 비슷해 아무 질문에나 어중간하게 걸린다."""
    java = _chunk("@SpringBootApplication\npublic class AirApplication {\n"
                  "    public static void main(String[] args) {\n"
                  "        SpringApplication.run(AirApplication.class, args);\n    }\n}")
    python = _chunk('if __name__ == "__main__":\n    main()', language="python")
    assert indexer.is_low_info(java) is True
    assert indexer.is_low_info(python) is True


def test_declaration_only_header_is_low_info():
    """작성자 주석 + 필드 선언만 있는 헤더. 파일마다 모양이 같아 서로 유사도가 높다."""
    header = _chunk("/*현석*/\n@Service\npublic class UserService {\n"
                    "    private final UserRepository userRepository;\n"
                    "    private final PasswordEncoder passwordEncoder;")
    assert indexer.is_low_info(header) is True


# ── 감점하면 안 되는 것 ──────────────────────────────────────

def test_inheritance_declaration_is_not_low_info():
    """상속 관계는 선언 한 줄뿐이어도 그 자체가 답이다.

    평가 질의 id_04("TextWebSocketHandler 상속")의 정답이 바로 이 헤더다 —
    선언만 있다고 뭉뚱그려 감점하면 그 질의가 다시 망가진다.
    """
    header = _chunk("//준영\npublic class ChatHandler extends TextWebSocketHandler {\n"
                    "    private static final Map<String, WebSocketSession> sessions;")
    assert indexer.is_low_info(header) is False


def test_real_method_is_not_low_info():
    method = _chunk("@Override\npublic void afterConnectionClosed(WebSocketSession session) {\n"
                    "    sessions.remove(session.getId());\n"
                    "    broadcast(\"퇴장\");\n}")
    assert indexer.is_low_info(method) is False


# ── 감점이 순서에 반영되는가 ─────────────────────────────────

@pytest.fixture
def active_build(monkeypatch):
    """검색은 활성 빌드 안에서만 찾는다. DB 없이 도는 테스트라 포인터를 대역으로 준다."""
    monkeypatch.setattr(
        indexer.index_status, "active_build_id", lambda snapshot_id, table=None: 7
    )
    return 7


def test_low_info_chunks_are_pushed_back(monkeypatch, active_build):
    """감점은 **제외가 아니다.** 뒤로 밀리되 목록에는 남는다."""
    rows = [
        _chunk("/* 스타일 */\n.a { color: red; }", language="css") | {"distance": 0.10},
        _chunk("public void save(Schedule s) {\n    repository.save(s);\n}") | {"distance": 0.12},
    ]
    monkeypatch.setattr(
        indexer.chunk_store, "search", lambda *a, **kw: [dict(r) for r in rows]
    )
    monkeypatch.setattr(indexer, "embed_query", lambda q: [0.0])

    found = indexer.search_code(1, "일정을 저장하는 코드는?", limit=2)

    # 거리 차(0.02)보다 감점(0.03)이 커서 순서가 뒤집힌다.
    assert [f["language"] for f in found] == ["java", "css"]


def test_candidates_are_fetched_wider_than_the_limit(monkeypatch, active_build):
    """상위 limit 개만 가져와 감점하면, 감점 대상에 밀려 못 들어온 근거가 영영 안 보인다."""
    asked = []

    def fake_search(build_id, vector, limit, table=None):
        asked.append(limit)
        return []

    monkeypatch.setattr(indexer.chunk_store, "search", fake_search)
    monkeypatch.setattr(indexer, "embed_query", lambda q: [0.0])

    indexer.search_code(1, "질문", limit=8)

    assert asked == [8 * indexer.CANDIDATE_MULTIPLIER]


def test_search_returns_nothing_without_an_active_build(monkeypatch):
    """활성 빌드가 없으면(첫 색인 진행 중) 검색하지 않는다 — 절반짜리 인덱스를 쓰면
    아직 임베딩하지 않은 코드가 '저장소에 없는 코드'처럼 보인다."""
    monkeypatch.setattr(
        indexer.index_status, "active_build_id", lambda snapshot_id, table=None: None
    )

    def fail_if_called(*a, **kw):
        raise AssertionError("활성 빌드가 없는데 검색했다")

    monkeypatch.setattr(indexer.chunk_store, "search", fail_if_called)

    assert indexer.search_code(1, "질문") == []
