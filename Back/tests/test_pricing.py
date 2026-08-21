"""단가 산정. LLM 을 부르지 않는다 (순수 계산)."""

from datetime import date, timedelta

import pytest

from app.services import claude_client as cc

LAST_INTRO_DAY = cc.SONNET_5_INTRO_LAST_DAY


def test_sonnet_uses_intro_price_through_the_last_day():
    assert cc.pricing_for("claude-sonnet-5", LAST_INTRO_DAY) == cc.SONNET_5_INTRO_PRICE


def test_sonnet_switches_to_list_price_the_next_day():
    """경계 하루 차이로 단가가 갈린다 — 마지막 날까지 도입가, 다음 날부터 정가."""
    assert (
        cc.pricing_for("claude-sonnet-5", LAST_INTRO_DAY + timedelta(days=1))
        == cc.SONNET_5_LIST_PRICE
    )


def test_cost_follows_the_date():
    """같은 토큰 수라도 시점이 다르면 비용이 다르다. 정가는 도입가의 1.5배다."""
    tokens = (1_000_000, 1_000_000)
    intro = cc.estimate_cost("claude-sonnet-5", *tokens, at=LAST_INTRO_DAY)
    listed = cc.estimate_cost(
        "claude-sonnet-5", *tokens, at=LAST_INTRO_DAY + timedelta(days=1)
    )

    assert intro == 12.0        # 2 + 10
    assert listed == 18.0       # 3 + 15


def test_date_defaults_to_today():
    """호출부는 날짜를 넘기지 않는다 — 기본값이 오늘이어야 기록이 자동으로 맞는다."""
    assert cc.pricing_for("claude-sonnet-5") == cc.pricing_for(
        "claude-sonnet-5", date.today()
    )


def test_flat_priced_model_ignores_the_date():
    at_any = date(2020, 1, 1)
    assert cc.pricing_for("claude-haiku-4-5", at_any) == cc.PRICING["claude-haiku-4-5"]


def test_unknown_model_has_no_price():
    """모르는 모델은 0 이 아니라 None 이다 — 0 으로 두면 공짜로 쓴 것처럼 집계된다."""
    assert cc.pricing_for("some-other-model") is None
    assert cc.estimate_cost("some-other-model", 1000, 1000) is None


# ── 캐시 토큰 ────────────────────────────────────────────────

def test_cache_write_costs_more_than_plain_input():
    """캐시 쓰기는 정가의 1.25배다. 같은 값으로 세면 25% 가 빈다."""
    plain = cc.estimate_cost("claude-haiku-4-5", 1_000_000, 0)
    written = cc.estimate_cost(
        "claude-haiku-4-5", 0, 0, cache_write_tokens=1_000_000
    )

    assert plain == 1.0
    assert written == 1.25


def test_cache_read_costs_a_tenth():
    read = cc.estimate_cost("claude-haiku-4-5", 0, 0, cache_read_tokens=1_000_000)

    assert read == pytest.approx(0.10)


def test_cache_tokens_are_added_not_substituted():
    """usage.input_tokens 는 캐시에 안 걸린 나머지만 센 값이라 셋을 더해야 한다.

    실측 회귀: 6턴 대화 세션에서 캐시 몫 12,620 토큰이 통째로 빠져 32% 과소 계상됐다.
    """
    with_cache = cc.estimate_cost(
        "claude-haiku-4-5",
        12_587,
        2_775,
        cache_write_tokens=7_211,
        cache_read_tokens=36_055,
        at=LAST_INTRO_DAY,
    )
    without_cache = cc.estimate_cost(
        "claude-haiku-4-5", 12_587, 2_775, at=LAST_INTRO_DAY
    )

    # 입력 12,587 + 쓰기 7,211×1.25 + 읽기 36,055×0.1 = 25,206.25 토큰
    assert with_cache == pytest.approx((25_206.25 * 1.0 + 2_775 * 5.0) / 1_000_000)
    assert with_cache > without_cache


def test_billable_tokens_counts_cache_tokens():
    """일일 상한은 단가가 아니라 처리된 토큰 수를 센다 — 캐시 몫도 실제로 처리된다."""
    result = {
        "input_tokens": 100,
        "output_tokens": 200,
        "cache_write_tokens": 5_000,
        "cache_read_tokens": 30_000,
    }

    assert cc.billable_tokens(result) == 35_300
