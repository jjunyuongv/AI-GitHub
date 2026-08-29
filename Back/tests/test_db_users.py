"""users / logins 쿼리를 **실제 PostgreSQL 로** 확인한다.

`tests/test_auth_api.py` 는 이 모듈을 대역으로 갈아끼우므로 SQL 자체는 거기서 안 돈다.
만료 판정처럼 SQL 안에서 하는 것은 대역으로는 영영 검증되지 않는다 — 그래서 여기가 있다.

DATABASE_URL 이 없으면 conftest 의 `db` 픽스처가 통째로 skip 한다.
"""

import pytest

from app.db import users
from app.db.pool import cursor

pytestmark = pytest.mark.usefixtures("db")

OCTOCAT = (4242, "octocat", "https://x/a.png")


def test_the_same_github_id_is_one_user_even_after_a_rename():
    """**키는 github_user_id 다.** 계정 이름은 바뀔 수 있다.

    이름을 키로 삼았다면 개명 한 번에 새 사용자가 생기고, 그 사람의 대화가 전부
    남의 것이 된다 — 소유자 검사가 그 위에 서 있으므로 조용히 틀리는 종류다.
    """
    first = users.upsert(*OCTOCAT)
    renamed = users.upsert(4242, "octocat-new", "https://x/b.png")

    assert first == renamed
    with cursor(commit=False) as cur:
        cur.execute("SELECT login, avatar_url FROM users WHERE id = %s", (first,))
        row = cur.fetchone()
    assert (row["login"], row["avatar_url"]) == ("octocat-new", "https://x/b.png")


def test_different_github_ids_are_different_users():
    """경계의 반대쪽. 없으면 모두를 한 사용자로 뭉치는 변이가 통과한다."""
    assert users.upsert(*OCTOCAT) != users.upsert(99, "someone", None)


def test_a_login_resolves_to_its_user():
    user_id = users.upsert(*OCTOCAT)

    found = users.get_login(users.create_login(user_id, days=14))

    assert (found["id"], found["login"]) == (user_id, "octocat")


def test_an_expired_login_resolves_to_nothing():
    """**만료는 SQL 이 판정한다.** 대역으로는 검증되지 않는 자리라 여기서 본다.

    음수 일수로 이미 지난 만료를 만든다 — 시계를 조작하지 않고 경계를 넘길 수 있다.
    """
    user_id = users.upsert(*OCTOCAT)

    assert users.get_login(users.create_login(user_id, days=-1)) is None


def test_an_unknown_login_resolves_to_nothing():
    assert users.get_login("00000000-0000-0000-0000-000000000000") is None


def test_deleting_a_login_takes_effect_immediately():
    """로그아웃이 진짜 로그아웃인지. **DB 세션을 고른 이유가 이것이다.**"""
    login_id = users.create_login(users.upsert(*OCTOCAT), days=14)

    users.delete_login(login_id)

    assert users.get_login(login_id) is None


def test_expired_rows_are_cleaned_but_live_ones_stay():
    """정리가 **살아 있는 로그인까지 지우지 않는지**를 함께 본다.

    한쪽만 보면 `DELETE FROM logins` 로 바꾸는 변이가 통과한다 — 그러면 정리가
    돌 때마다 모두가 로그아웃된다.
    """
    user_id = users.upsert(*OCTOCAT)
    alive = users.create_login(user_id, days=14)
    users.create_login(user_id, days=-1)

    assert users.delete_expired() == 1
    assert users.get_login(alive) is not None
