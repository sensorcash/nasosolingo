"""Тесты игровой экономики. Без БД — чистая логика."""
from datetime import date, datetime, timedelta, timezone

from app.game import economy as ec

T0 = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)
HALF_HOUR = ec.LIFE_REGEN_SECONDS


# ---------- жизни ----------

def test_full_lives_do_not_regen():
    r = ec.regen_lives(5, T0 - timedelta(hours=10), T0)
    assert r.lives == 5
    assert r.seconds_to_next is None


def test_regen_one_life_after_interval():
    r = ec.regen_lives(3, T0 - timedelta(seconds=HALF_HOUR), T0)
    assert r.lives == 4


def test_no_regen_before_interval():
    r = ec.regen_lives(3, T0 - timedelta(seconds=HALF_HOUR - 60), T0)
    assert r.lives == 3
    assert r.seconds_to_next == 60


def test_regen_remainder_is_not_lost():
    """50 минут = 1 жизнь + 20 минут остатка. Остаток должен перенестись."""
    r = ec.regen_lives(2, T0 - timedelta(minutes=50), T0)
    assert r.lives == 3
    assert r.seconds_to_next == 10 * 60      # до следующей осталось 10 минут, а не 30


def test_regen_caps_at_max():
    r = ec.regen_lives(1, T0 - timedelta(days=3), T0)
    assert r.lives == ec.MAX_LIVES
    assert r.seconds_to_next is None


def test_regen_survives_clock_skew():
    """Время «в будущем» не должно ломать расчёт."""
    r = ec.regen_lives(2, T0 + timedelta(hours=1), T0)
    assert r.lives == 2


def test_spend_lives():
    r = ec.spend_lives(5, T0 - timedelta(days=1), 2, T0)
    assert r.lives == 3
    assert r.seconds_to_next == HALF_HOUR    # таймер стартовал заново


def test_spend_never_below_zero():
    r = ec.spend_lives(1, T0, 5, T0)
    assert r.lives == 0


def test_spend_zero_is_noop():
    r = ec.spend_lives(4, T0, 0, T0)
    assert r.lives == 4


# ---------- поток ----------

D = date(2026, 7, 23)


def test_streak_starts_at_one():
    assert ec.update_streak(0, None, D) == (1, D)


def test_streak_same_day_unchanged():
    assert ec.update_streak(5, D, D) == (5, D)


def test_streak_consecutive_day_increments():
    assert ec.update_streak(5, D, D + timedelta(days=1)) == (6, D + timedelta(days=1))


def test_streak_resets_after_gap():
    assert ec.update_streak(9, D, D + timedelta(days=3)) == (1, D + timedelta(days=3))


def test_streak_ignores_past_events():
    """Событие из офлайн-очереди «задним числом» не должно сбивать поток."""
    assert ec.update_streak(7, D, D - timedelta(days=2)) == (7, D)


def test_local_date_uses_user_timezone():
    """23:30 UTC — это уже следующий день в Москве."""
    night = datetime(2026, 7, 23, 23, 30, tzinfo=timezone.utc)
    assert ec.local_date(night, "Europe/Moscow") == date(2026, 7, 24)
    assert ec.local_date(night, "UTC") == date(2026, 7, 23)


def test_local_date_bad_timezone_falls_back():
    assert ec.local_date(T0, "Ерунда/Неизвестно") == date(2026, 7, 23)


# ---------- опыт и уровни ----------

def test_xp_perfect_lesson():
    # 15 базовых + 5*4 за ответы + 10 за идеал = 45 (как в прототипе)
    assert ec.xp_for_lesson(5, 5, is_repeat=False) == 45


def test_xp_with_mistakes_has_no_perfect_bonus():
    assert ec.xp_for_lesson(3, 5, is_repeat=False) == 15 + 12


def test_xp_repeat_is_reduced():
    full = ec.xp_for_lesson(5, 5, is_repeat=False)
    repeat = ec.xp_for_lesson(5, 5, is_repeat=True)
    assert repeat < full
    assert repeat == int(full * ec.XP_REPEAT_MULTIPLIER)


def test_xp_clamps_impossible_input():
    """Правильных больше, чем вопросов — не должно раздувать опыт."""
    assert ec.xp_for_lesson(99, 5, is_repeat=False) == ec.xp_for_lesson(5, 5, is_repeat=False)


def test_levels_grow_monotonically():
    assert ec.level_for_xp(0) == 1
    prev = 1
    for xp in range(0, 20000, 137):
        lvl = ec.level_for_xp(xp)
        assert lvl >= prev
        prev = lvl


def test_level_thresholds_match():
    first = ec.LEVEL_THRESHOLDS[1]
    assert ec.level_for_xp(first - 1) == 1
    assert ec.level_for_xp(first) == 2


def test_xp_to_next_level():
    assert ec.xp_to_next_level(0) == ec.LEVEL_THRESHOLDS[1]
    assert ec.xp_to_next_level(10**9) is None      # максимум достигнут
