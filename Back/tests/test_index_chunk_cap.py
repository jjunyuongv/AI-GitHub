"""청크 상한 판정과 감시선. DB 도 임베딩 모델도 쓰지 않는다 (순수 경계 판정).

상한을 넘겼을 때 실제로 무엇이 저장되는지와 `start()` 가 재시도를 막는지는
DB 가 필요해서 `test_indexer.py`·`test_db_index_status.py` 에 있다.
"""

import logging

import pytest

from app.services import indexer, oauth


@pytest.fixture
def cap(monkeypatch):
    """상한 10 · 경고 문턱 8(=10×0.8). skip() 은 부른 인자만 받아 둔다."""
    calls = []
    monkeypatch.setattr(indexer, "MAX_INDEX_CHUNKS", 10)
    monkeypatch.setattr(indexer.index_status, "skip", lambda *a: calls.append(a))
    return calls


# ── 상한: 경계 양쪽을 고정한다 ────────────────────────────────────────────────
# 딱 상한인 것과 하나 넘은 것을 둘 다 둔다. 한쪽만 두면 `<=` 를 `<` 로 바꿔도
# 결과가 같아 테스트가 그 판정을 안 재게 된다.


def test_exactly_at_the_cap_is_indexed(cap):
    assert indexer._skip_over_cap(1, "o", "r", 10) is False
    assert cap == []


def test_one_over_the_cap_is_skipped(cap):
    assert indexer._skip_over_cap(1, "o", "r", 11) is True
    assert len(cap) == 1


def test_skip_records_the_actual_count_and_both_numbers(cap):
    """화면이 "몇 개라서 넘었는지"를 보여주려면 실제 수가 저장돼야 한다."""
    indexer._skip_over_cap(7, "o", "r", 4365)
    build_id, chunks, reason = cap[0]

    assert (build_id, chunks) == (7, 4365)
    assert "4,365" in reason and "10" in reason


def test_zero_cap_never_skips(monkeypatch, cap):
    """0 이면 제한을 끈다 — 다른 상한들과 같은 관용구다."""
    monkeypatch.setattr(indexer, "MAX_INDEX_CHUNKS", 0)

    assert indexer._skip_over_cap(1, "o", "r", 999_999) is False
    assert cap == []


def test_a_failed_skip_record_still_reports_over_cap(cap, monkeypatch):
    """표시를 못 남겨도 색인은 진행하지 않는다 — 넘은 것은 넘은 것이다."""
    def boom(*a):
        raise indexer.DB_ERRORS[0]("DB 없음")

    monkeypatch.setattr(indexer.index_status, "skip", boom)

    assert indexer._skip_over_cap(1, "o", "r", 11) is True


@pytest.mark.parametrize("client_id", ["", "test-client-id"])
@pytest.mark.parametrize("chunks,skipped", [(10, False), (11, True)])
def test_상한은_로그인_여부와_무관하다(cap, monkeypatch, client_id, chunks, skipped):
    """로그인이 여는 것은 **어떤 저장소를 받나**이지 **얼마나 색인하나**가 아니다.

    허용 목록이 로그인으로 갈리게 되면서(`services/allowlist.py`) 같은 임포트가
    여기까지 뻗을 수 있다. `_skip_over_cap` 앞에 `if oauth.enabled(): return False`
    를 넣는 변이는 **네 조합 중 `("test-client-id", 11)` 하나에서만** 깨진다 —
    그래서 상한 경계 양쪽과 로그인 양쪽을 모두 둔다.
    """
    monkeypatch.setattr(oauth, "GITHUB_OAUTH_CLIENT_ID", client_id)

    assert indexer._skip_over_cap(1, "o", "r", chunks) is skipped


# ── 감시선: 여기도 경계 양쪽 ──────────────────────────────────────────────────


def _warned(caplog) -> bool:
    # getMessage() 로 편다. r.message 는 이미 펴진 문자열이라 다시 % 를 걸면
    # 본문의 '%' 를 형식 문자로 읽어 ValueError 가 난다 (실제로 겪었다).
    return any("상한에 가깝습니다" in r.getMessage() for r in caplog.records)


def test_just_under_the_warn_threshold_is_quiet(cap, caplog):
    """문턱 8 바로 아래(7)에서는 아무 말도 하지 않는다."""
    with caplog.at_level(logging.WARNING, logger=indexer.logger.name):
        indexer._warn_if_near_cap("o", "r", 7)

    assert not _warned(caplog)


def test_at_the_warn_threshold_it_warns(cap, caplog):
    """문턱에 닿으면(8) 알린다. 색인은 그대로 진행한다."""
    with caplog.at_level(logging.WARNING, logger=indexer.logger.name):
        indexer._warn_if_near_cap("o", "r", 8)

    assert _warned(caplog)


def test_zero_cap_never_warns(monkeypatch, caplog):
    """상한이 꺼져 있으면 문턱도 없다.

    `chunks < 0 * 0.8` 은 언제나 거짓이라, 따로 막지 않으면 **모든 색인이 경고를 낸다.**
    """
    monkeypatch.setattr(indexer, "MAX_INDEX_CHUNKS", 0)

    with caplog.at_level(logging.WARNING, logger=indexer.logger.name):
        indexer._warn_if_near_cap("o", "r", 999_999)

    assert not _warned(caplog)


def test_the_warn_ratio_leaves_room_before_the_cap():
    """경고가 상한 **아래**에서 떠야 손 쓸 여유가 생긴다. 1.0 이면 감시선이 아니다."""
    assert 0 < indexer.CHUNK_CAP_WARN_RATIO < 1
