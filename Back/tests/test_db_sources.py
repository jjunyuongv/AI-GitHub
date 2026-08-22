"""snapshot_source_files 통합 테스트. 실제 PostgreSQL 이 필요하다 (없으면 skip).

**여기서 지키는 것은 하나다: 넣은 것과 꺼낸 것이 글자 하나 다르지 않을 것.**
이 표의 존재 이유가 "청크로는 원본을 복원할 수 없다"이므로, 보관한 원문마저
조용히 달라지면 표를 만든 의미가 없다.
"""

import pytest

from app.db import repos as repo_db
from app.db import sources as source_store
from app.db.pool import cursor
from app.services import cleanup

pytestmark = pytest.mark.usefixtures("db")

SNAPSHOT = {
    "owner": "react",
    "name": "react",
    "display_owner": "React",
    "display_name": "React",
    "key_source": "pushed_at",
    "version": "20260814091233",
    "context": "## 레포지토리 정보",
    "summary": "요약 본문",
    "model": "claude-sonnet-5",
}

# 원문이 그대로 돌아오는지 재려면 **평범한 파일로는 부족하다.** 실제 저장소에서
# 오는 것들을 넣는다 — 한국어 주석, CRLF, 탭, 끝 개행 없는 파일, 그리고
# fetch_source_files 가 errors="replace" 로 만드는 치환문자(U+FFFD).
FILES = {
    "app/main.py": "# 한국어 주석입니다\ndef run():\n\treturn 1\n",
    "src/win.js": "const a = 1;\r\nconst b = 2;\r\n",
    "src/no_newline.css": ".a { color: red; }",
    "src/broken.py": "s = '�'\n",
    "a/b/c/deep.java": "public class C {}\n",
}


@pytest.fixture
def snapshot_id() -> int:
    return repo_db.put_snapshot(**SNAPSHOT)["id"]


def _other_snapshot() -> int:
    """같은 저장소의 다른 버전. repo 행은 재사용되고 스냅샷만 늘어난다."""
    return repo_db.put_snapshot(**{**SNAPSHOT, "version": "20260901000000"})["id"]


def _count_all() -> int:
    with cursor(commit=False) as cur:
        cur.execute("SELECT count(*) AS n FROM snapshot_source_files")
        return cur.fetchone()["n"]


# --- 바이트 단위 동일 ---------------------------------------------------------


def test_stored_source_comes_back_unchanged(snapshot_id):
    """넣은 것과 꺼낸 것이 완전히 같아야 한다. 이 표의 유일한 계약이다."""
    assert source_store.put_files(snapshot_id, FILES) == len(FILES)

    for path, content in FILES.items():
        assert source_store.get_file(snapshot_id, path) == content


def test_missing_file_is_none(snapshot_id):
    source_store.put_files(snapshot_id, FILES)

    assert source_store.get_file(snapshot_id, "app/does_not_exist.py") is None


def test_paths_come_back_sorted(snapshot_id):
    source_store.put_files(snapshot_id, FILES)

    assert source_store.list_paths(snapshot_id) == sorted(FILES)


def test_empty_source_stores_nothing(snapshot_id):
    """소스가 없는 저장소도 오류 없이 지나간다 (색인이 청크 0개로 끝나는 경우)."""
    assert source_store.put_files(snapshot_id, {}) == 0
    assert source_store.count(snapshot_id) == 0


# --- 스냅샷 단위 --------------------------------------------------------------


def test_snapshots_do_not_share_sources(snapshot_id):
    """**같은 경로라도 스냅샷이 다르면 다른 파일이다.**

    세션이 보는 코드 버전은 스냅샷으로 확정된다. 여기가 섞이면 진행 중인 대화가
    자기가 보던 것과 다른 코드를 읽는다.
    """
    other = _other_snapshot()
    source_store.put_files(snapshot_id, {"app/main.py": "옛 내용\n"})
    source_store.put_files(other, {"app/main.py": "새 내용\n"})

    assert source_store.get_file(snapshot_id, "app/main.py") == "옛 내용\n"
    assert source_store.get_file(other, "app/main.py") == "새 내용\n"


def test_reput_replaces_in_place(snapshot_id):
    """재색인이 파일이 줄어든 소스를 넣으면 옛 행이 남지 않는다.

    upsert 였다면 사라진 파일이 그대로 남아, 도구가 저장소에 없는 파일을 읽어 준다.
    """
    source_store.put_files(snapshot_id, {"a.py": "1\n", "b.py": "2\n", "c.py": "3\n"})

    source_store.put_files(snapshot_id, {"a.py": "새 내용\n", "b.py": "2\n"})

    assert source_store.list_paths(snapshot_id) == ["a.py", "b.py"]
    assert source_store.get_file(snapshot_id, "a.py") == "새 내용\n"
    assert source_store.get_file(snapshot_id, "c.py") is None


def test_reput_does_not_touch_other_snapshots(snapshot_id):
    other = _other_snapshot()
    source_store.put_files(snapshot_id, {"a.py": "이쪽\n"})
    source_store.put_files(other, {"a.py": "저쪽\n"})

    source_store.put_files(snapshot_id, {"a.py": "이쪽 갱신\n"})

    assert source_store.get_file(other, "a.py") == "저쪽\n"


# --- grep ---------------------------------------------------------------------


def test_grep_finds_the_line_and_its_number(snapshot_id):
    source_store.put_files(snapshot_id, {"a.py": "import os\ndef find_user():\n    pass\n"})

    hits = source_store.grep(snapshot_id, "find_user", limit=10)

    assert hits == [{"path": "a.py", "line": 2, "text": "def find_user():"}]


def test_grep_is_case_insensitive(snapshot_id):
    source_store.put_files(snapshot_id, {"a.py": "class UserService:\n"})

    assert source_store.grep(snapshot_id, "userservice", limit=10)


def test_grep_strips_the_carriage_return(snapshot_id):
    """CRLF 파일에서 모든 줄이 `\\r` 로 끝나면 인용이 한 글자씩 어긋난다."""
    source_store.put_files(snapshot_id, {"win.js": "const a = 1;\r\nconst b = 2;\r\n"})

    hits = source_store.grep(snapshot_id, "const b", limit=10)

    assert hits[0]["text"] == "const b = 2;"


def test_grep_escapes_like_wildcards(snapshot_id):
    """`_` 는 LIKE 와일드카드다. 이스케이프하지 않으면 없는 이름을 있다고 답한다."""
    source_store.put_files(snapshot_id, {"a.py": "def findXuser():\n    pass\n"})

    assert source_store.grep(snapshot_id, "find_user", limit=10) == []


def test_grep_stays_inside_the_snapshot(snapshot_id):
    other = _other_snapshot()
    source_store.put_files(snapshot_id, {"a.py": "needle here\n"})
    source_store.put_files(other, {"a.py": "needle there\n"})

    hits = source_store.grep(snapshot_id, "needle", limit=10)

    assert [h["text"] for h in hits] == ["needle here"]


def test_grep_respects_the_limit(snapshot_id):
    source_store.put_files(snapshot_id, {"a.py": "hit\n" * 40})

    assert len(source_store.grep(snapshot_id, "hit", limit=30)) == 30


def test_grep_returns_paths_in_order(snapshot_id):
    source_store.put_files(
        snapshot_id, {"z.py": "needle\n", "a.py": "needle\n", "m.py": "needle\n"}
    )

    assert [h["path"] for h in source_store.grep(snapshot_id, "needle", limit=10)] == [
        "a.py", "m.py", "z.py",
    ]


def test_grep_without_a_pattern_finds_nothing(snapshot_id):
    """빈 패턴을 그대로 넘기면 `%%` 가 되어 저장소 전체가 돌아온다."""
    source_store.put_files(snapshot_id, FILES)

    assert source_store.grep(snapshot_id, "", limit=10) == []


# --- 정리와 함께 사라지는가 ---------------------------------------------------


def test_deleting_the_snapshot_takes_the_sources(snapshot_id):
    source_store.put_files(snapshot_id, FILES)

    with cursor() as cur:
        cur.execute("DELETE FROM repo_snapshots WHERE id = %s", (snapshot_id,))

    assert _count_all() == 0


def test_cleanup_of_an_orphan_snapshot_takes_the_sources(snapshot_id):
    """`cleanup.run(apply=True)` 이 지우는 경로로도 확인한다.

    CASCADE 를 직접 부르는 것과 실제 정리 경로는 다른 조건을 탄다 — 고아 스냅샷은
    '대화가 없고 그 저장소의 최신도 아닌' 것이다. 그 조건을 실제로 만들어서 잰다.
    """
    newest = _other_snapshot()          # snapshot_id 를 최신이 아니게 만든다
    source_store.put_files(snapshot_id, FILES)
    source_store.put_files(newest, {"keep.py": "남는다\n"})

    result = cleanup.run(apply=True)

    assert result["deleted"]["orphan_snapshots"] == 1
    assert source_store.count(snapshot_id) == 0
    assert source_store.get_file(newest, "keep.py") == "남는다\n"
