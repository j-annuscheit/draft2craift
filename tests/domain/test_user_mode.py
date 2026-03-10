from shared.domain.user_mode import (
    USER_MODE_PLUS,
    USER_MODE_SIMPLE,
    mode_rank,
    normalize_user_mode,
)


def test_normalize_user_mode_defaults_to_plus():
    assert normalize_user_mode("unknown") == USER_MODE_PLUS


def test_mode_rank_order_is_stable():
    assert mode_rank(USER_MODE_SIMPLE) < mode_rank(USER_MODE_PLUS)
