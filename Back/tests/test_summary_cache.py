import psycopg
import pytest

from app.db import pool
from app.services import summary_cache

ACCESS = {
    "owner": "React",  # 정식 표기(대문자 포함)
    "name": "React",
    "pushed_at": "2026-08-14T09:12:33Z",
    "default_branch": "main",
}


# --- 키 생성 ----------------------------------------------------------------
# 키 규칙은 DB 의 (repo, key_source, version) 세 열로 그대로 들어간다.


def test_key_uses_canonical_name_lowercased():
    """리다이렉트 대비: 입력이 아니라 정식 표기를 소문자화해서 쓴다."""
    assert summary_cache.build_key(ACCESS).startswith("react/react@")


def test_key_records_what_it_was_built_from():
    """나중에 SHA로 바꿔도 옛 키와 섞이지 않도록 출처를 키에 넣는다."""
    assert summary_cache.build_key(ACCESS) == "react/react@pushed_at:20260814091233"


@pytest.mark.parametrize(
    "pushed_at",
    [
        "2026-08-14T09:12:33Z",
        "2026-08-14T09:12:33+00:00",
        "2026-08-14T18:12:33+09:00",  # 같은 시각, 다른 타임존 표기
    ],
)
def test_timezone_notation_does_not_change_key(pushed_at):
    assert summary_cache.build_key({**ACCESS, "pushed_at": pushed_at}) == summary_cache.build_key(
        ACCESS
    )


def test_key_has_no_colon_from_timestamp():
    """콜론·하이픈 같은 구분자가 타임스탬프에서 넘어오지 않는다."""
    version = summary_cache.build_key(ACCESS).split("pushed_at:")[1]
    assert version.isdigit()


def test_push_changes_the_key():
    updated = {**ACCESS, "pushed_at": "2026-08-15T00:00:00Z"}
    assert summary_cache.build_key(updated) != summary_cache.build_key(ACCESS)


def test_malformed_timestamp_still_builds_a_key():
    key = summary_cache.build_key({**ACCESS, "pushed_at": "not-a-date"})
    assert key.startswith("react/react@")


# --- 저장·조회 (실제 DB 필요) ------------------------------------------------


def test_miss_then_hit(db):
    assert summary_cache.get(ACCESS) is None

    summary_cache.put(ACCESS, model="claude-sonnet-5", summary="요약 본문", context="원문")

    found = summary_cache.get(ACCESS)
    assert found["summary"] == "요약 본문"
    assert found["model"] == "claude-sonnet-5"
    # 후속 질문이 재사용할 컨텍스트도 같은 행에 들어 있다.
    assert found["context"] == "원문"
    assert found["id"]


def test_updated_repo_misses_cache(db):
    summary_cache.put(ACCESS, model="m", summary="옛 요약", context="원문")

    updated = {**ACCESS, "pushed_at": "2026-08-15T00:00:00Z"}

    assert summary_cache.get(updated) is None


def test_new_version_makes_a_new_snapshot(db):
    """파일 캐시 시절과 달라진 점: 옛 스냅샷을 지우지 않는다.

    진행 중인 대화가 옛 스냅샷을 참조하고 있어서, 지우면 후속 질문이 볼 코드가 사라진다.
    """
    old = summary_cache.put(ACCESS, model="m", summary="옛 요약", context="옛 원문")
    updated = {**ACCESS, "pushed_at": "2026-08-15T00:00:00Z"}
    new = summary_cache.put(updated, model="m", summary="새 요약", context="새 원문")

    assert old["id"] != new["id"]
    assert summary_cache.get(ACCESS)["summary"] == "옛 요약"
    assert summary_cache.get(updated)["summary"] == "새 요약"


def test_other_repos_are_untouched(db):
    other = {**ACCESS, "owner": "psf", "name": "requests"}
    summary_cache.put(ACCESS, model="m", summary="react 요약", context="원문")
    summary_cache.put(other, model="m", summary="requests 요약", context="원문")

    assert summary_cache.get(ACCESS)["summary"] == "react 요약"
    assert summary_cache.get(other)["summary"] == "requests 요약"


# --- 실패해도 서비스는 계속 -------------------------------------------------
# DB 가 죽어도 분석 자체는 (캐시 없이) 돌아가야 한다. 예외를 올리지 않고 경고만 남긴다.


def test_read_failure_looks_like_a_miss(monkeypatch):
    def boom(**kwargs):
        raise psycopg.OperationalError("연결 실패")

    monkeypatch.setattr(summary_cache.repo_db, "get_snapshot", boom)

    assert summary_cache.get(ACCESS) is None


def test_write_failure_does_not_raise(monkeypatch):
    def boom(**kwargs):
        raise psycopg.OperationalError("연결 실패")

    monkeypatch.setattr(summary_cache.repo_db, "put_snapshot", boom)

    # 예외가 올라오면 분석 전체가 실패한다. None 을 돌려주고 넘어가야 한다.
    assert summary_cache.put(ACCESS, model="m", summary="본문", context="원문") is None


def test_no_database_url_is_a_miss(monkeypatch):
    """DB 를 아예 안 쓰는 설정에서도 /analyze 는 (캐시 없이) 돌아야 한다."""
    monkeypatch.setattr(pool, "DATABASE_URL", "")

    assert summary_cache.get(ACCESS) is None
    assert summary_cache.put(ACCESS, model="m", summary="본문", context="원문") is None
