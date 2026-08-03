"""Игровая экономика — чистые функции, без БД и без побочных эффектов.

Всё, что здесь, легко тестируется и легко крутится (баланс правится в одном месте).
Правило: время всегда приходит аргументом, никаких скрытых datetime.now() внутри.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ---------- настройки баланса ----------

MAX_LIVES = 5
LIFE_REGEN_SECONDS = 30 * 60          # +1 жизнь каждые 30 минут

XP_PER_CORRECT = 4                     # как в прототипе
XP_LESSON_BONUS = 15
XP_PERFECT_BONUS = 10
XP_REPEAT_MULTIPLIER = 0.3             # повторное прохождение — 30% опыта
XP_PER_REVIEW_CORRECT = 2              # опыт за верный ответ в разборе ошибок

DEFAULT_DAILY_GOAL_XP = 20             # дневная цель по умолчанию
DAILY_GOAL_CHOICES = [10, 20, 40, 70]  # варианты на выбор игроку

REVIEW_BATCH_SIZE = 12                 # сколько вопросов даём в одном разборе

# Заморозка потока: пропущенный день не обнуляет поток, если есть заморозка.
STREAK_FREEZE_START = 2                # сколько даём новичку
STREAK_FREEZE_MAX = 5                  # потолок запаса
STREAK_FREEZE_EVERY = 7               # +1 заморозка за каждые 7 дней потока

FAST_LESSON_SECONDS = 40              # урок быстрее этого — «быстрая рука"

MAX_LEVEL = 100


# ---------- жизни ----------

@dataclass(frozen=True)
class LivesResult:
    lives: int
    updated_at: datetime
    seconds_to_next: int | None        # None, если жизни полные


def regen_lives(lives: int, updated_at: datetime, now: datetime) -> LivesResult:
    """Досчитать жизни, накопившиеся с момента updated_at.

    Ключевая тонкость: остаток времени НЕ теряется. Если прошло 50 минут,
    начисляем 1 жизнь, а «лишние» 20 минут переносим — иначе игрок незаметно
    терял бы прогресс таймера при каждом заходе в приложение.
    """
    if lives >= MAX_LIVES:
        return LivesResult(MAX_LIVES, now, None)

    elapsed = (now - updated_at).total_seconds()
    if elapsed < 0:                                  # часы клиента/сервера разъехались
        elapsed = 0

    gained = int(elapsed // LIFE_REGEN_SECONDS)
    if gained <= 0:
        remainder = elapsed % LIFE_REGEN_SECONDS
        return LivesResult(lives, updated_at, int(LIFE_REGEN_SECONDS - remainder))

    new_lives = min(MAX_LIVES, lives + gained)
    if new_lives >= MAX_LIVES:
        return LivesResult(MAX_LIVES, now, None)

    # переносим остаток: сдвигаем точку отсчёта ровно на выданные жизни
    new_updated = updated_at + timedelta(seconds=gained * LIFE_REGEN_SECONDS)
    remainder = (now - new_updated).total_seconds()
    return LivesResult(new_lives, new_updated, int(LIFE_REGEN_SECONDS - remainder))


def spend_lives(lives: int, updated_at: datetime, count: int, now: datetime) -> LivesResult:
    """Списать жизни за ошибки. Не уходим ниже нуля.

    Если до списания жизни были полные — запускаем таймер регенерации от now.
    """
    if count <= 0:
        return LivesResult(lives, updated_at, None if lives >= MAX_LIVES else 0)

    was_full = lives >= MAX_LIVES
    new_lives = max(0, lives - count)
    new_updated = now if was_full else updated_at
    return regen_lives(new_lives, new_updated, now)


def grant_lives(lives: int, updated_at: datetime, count: int, now: datetime) -> LivesResult:
    """Вернуть жизни (например, за пройденный разбор ошибок). Не выше максимума.

    Сначала досчитываем накопленное по времени, потом добавляем count.
    Таймер регенерации не сбрасываем — «недокопленное» время сохраняется.
    """
    res = regen_lives(lives, updated_at, now)
    if count <= 0:
        return res
    new_lives = min(MAX_LIVES, res.lives + count)
    if new_lives >= MAX_LIVES:
        return LivesResult(MAX_LIVES, now, None)
    return LivesResult(new_lives, res.updated_at, res.seconds_to_next)


# ---------- поток (streak) ----------

def local_date(now: datetime, tz_name: str) -> date:
    """Календарная дата в таймзоне пользователя.

    Важно: поток считается по местному дню игрока, а не по UTC — иначе
    для Москвы «день» заканчивался бы в 3 часа ночи.
    """
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        tz = timezone.utc
    return now.astimezone(tz).date()


def update_streak(streak: int, last_active: date | None, today: date) -> tuple[int, date]:
    """Пересчитать поток при активности в день today."""
    if last_active is None:
        return 1, today
    if today == last_active:
        return streak, last_active          # сегодня уже засчитано
    if today == last_active + timedelta(days=1):
        return streak + 1, today            # подряд
    if today < last_active:
        return streak, last_active          # защита от «прошлого» события из офлайн-очереди
    return 1, today                         # пропуск — поток сгорел


def apply_streak(streak: int, last_active: date | None, today: date, freezes: int):
    """Поток с заморозкой. Возвращает (поток, дата, заморозки, потрачено, начислено).

    Заморозки списываются лениво — при следующей активности, если между ней и
    прошлым днём был пропуск. Это в духе всей механики: ничего не тикает в фоне,
    всё досчитывается по факту захода. За каждые 7 дней потока даём +1 заморозку.
    """
    if last_active is None:
        new_streak, new_last = 1, today
    elif today == last_active:
        return streak, last_active, freezes, 0, 0        # сегодня уже засчитано
    elif today < last_active:
        return streak, last_active, freezes, 0, 0        # прошлое из офлайн-очереди
    elif today == last_active + timedelta(days=1):
        new_streak, new_last, consumed = streak + 1, today, 0
    else:
        missed = (today - last_active).days - 1          # сколько дней пропущено
        if freezes >= missed:
            freezes -= missed
            new_streak, new_last, consumed = streak + 1, today, missed
        else:
            new_streak, new_last, consumed = 1, today, 0  # заморозок не хватило

    old = streak if last_active is not None else 0
    earned = 1 if (new_streak > old and new_streak % STREAK_FREEZE_EVERY == 0) else 0
    freezes = min(STREAK_FREEZE_MAX, freezes + earned)
    return new_streak, new_last, freezes, locals().get("consumed", 0), earned


# ---------- опыт и уровни ----------

def xp_for_lesson(correct: int, total: int, is_repeat: bool) -> int:
    """Опыт за урок. Считает СЕРВЕР по присланным ответам, а не клиент."""
    correct = max(0, min(correct, total))
    xp = XP_LESSON_BONUS + correct * XP_PER_CORRECT
    if total > 0 and correct == total:
        xp += XP_PERFECT_BONUS
    if is_repeat:
        xp = int(xp * XP_REPEAT_MULTIPLIER)
    return xp


def xp_for_review(correct: int) -> int:
    """Опыт за разбор ошибок. Меньше, чем за урок: это повторение, не новый материал."""
    return max(0, correct) * XP_PER_REVIEW_CORRECT


# ---------- дневная цель ----------

def apply_daily_progress(
    daily_xp: int, daily_date: date | None, today: date, gained: int
) -> tuple[int, date]:
    """Прибавить опыт к дневному счётчику, сбрасывая его в новый день.

    Хранение «сколько набрано сегодня» вместо пересчёта по логу событий —
    дешевле и не требует запроса по всей истории при каждом открытии экрана.
    """
    if daily_date != today:
        return max(0, gained), today
    return daily_xp + max(0, gained), today


def daily_state(
    daily_xp: int, daily_date: date | None, goal: int, today: date
) -> tuple[int, int, bool]:
    """Актуальный прогресс дня: (набрано, цель, цель достигнута).

    Если последняя активность была вчера — сегодня счётчик уже нулевой,
    даже если в базе ещё лежит вчерашнее число.
    """
    current = daily_xp if daily_date == today else 0
    goal = goal if goal and goal > 0 else DEFAULT_DAILY_GOAL_XP
    return current, goal, current >= goal


def _level_thresholds() -> list[int]:
    """Накопительный порог опыта для каждого уровня.

    Шаг растёт: 100, 150, 200, 250... Уровень 1 — с нуля.
    """
    out = [0]
    total = 0
    for lvl in range(1, MAX_LEVEL):
        total += 50 + 50 * lvl
        out.append(total)
    return out


LEVEL_THRESHOLDS = _level_thresholds()


def level_for_xp(xp: int) -> int:
    lvl = 1
    for i, threshold in enumerate(LEVEL_THRESHOLDS, start=1):
        if xp >= threshold:
            lvl = i
        else:
            break
    return lvl


def xp_to_next_level(xp: int) -> int | None:
    """Сколько опыта до следующего уровня. None — если достигнут максимум."""
    lvl = level_for_xp(xp)
    if lvl >= MAX_LEVEL:
        return None
    return LEVEL_THRESHOLDS[lvl] - xp


# ---------- достижения (ачивки) ----------
# Каждая ачивка — id, название, описание, иконка и условие по накопленной
# статистике игрока. Условия — чистые функции, БД тут не трогается: сервис
# собирает stats и прогоняет каталог. Иконки берутся из набора web/img/icons/.

ACHIEVEMENTS = [
    {"id": "first_lesson", "title": "Первый пуск", "icon": "done",
     "desc": "Пройден первый урок",
     "cond": lambda s: s["lessons_done"] >= 1},
    {"id": "ten_lessons", "title": "Разогрелся", "icon": "lesson",
     "desc": "Пройдено 10 уроков",
     "cond": lambda s: s["lessons_done"] >= 10},
    {"id": "all_lessons", "title": "Мастер водоснабжения", "icon": "level",
     "desc": "Пройдено 30 уроков",
     "cond": lambda s: s["lessons_done"] >= 30},
    {"id": "perfectionist", "title": "Без единой ошибки", "icon": "ok",
     "desc": "5 уроков идеально",
     "cond": lambda s: s["perfect_lessons"] >= 5},
    {"id": "goal_getter", "title": "Цель дня взята", "icon": "goal",
     "desc": "Выполнена дневная цель",
     "cond": lambda s: s["daily_goal_met"]},
    {"id": "reviewer", "title": "Работа над ошибками", "icon": "review",
     "desc": "5 разборов ошибок",
     "cond": lambda s: s["reviews_done"] >= 5},
    {"id": "streak_3", "title": "Три дня подряд", "icon": "streak",
     "desc": "Поток 3 дня",
     "cond": lambda s: s["streak"] >= 3},
    {"id": "streak_7", "title": "Неделя в потоке", "icon": "streak",
     "desc": "Поток 7 дней",
     "cond": lambda s: s["streak"] >= 7},
    {"id": "streak_30", "title": "Месяц дисциплины", "icon": "streak",
     "desc": "Поток 30 дней",
     "cond": lambda s: s["streak"] >= 30},
    {"id": "level_5", "title": "Пятый уровень", "icon": "level",
     "desc": "Достигнут 5-й уровень",
     "cond": lambda s: s["level"] >= 5},
    {"id": "unit_done", "title": "Юнит закрыт", "icon": "done",
     "desc": "Пройден целый юнит",
     "cond": lambda s: s.get("units_done", 0) >= 1},
    {"id": "xp_500", "title": "Пятьсот опыта", "icon": "xp",
     "desc": "Накоплено 500 опыта",
     "cond": lambda s: s.get("xp", 0) >= 500},
    {"id": "speed", "title": "Быстрая рука", "icon": "time",
     "desc": "Урок пройден быстрее 40 секунд",
     "cond": lambda s: s.get("fast_lesson", False)},
    {"id": "comeback", "title": "Спасён заморозкой", "icon": "streak",
     "desc": "Заморозка спасла поток",
     "cond": lambda s: s.get("streak_saved", False)},
    {"id": "freeze_max", "title": "Запасливый", "icon": "streak",
     "desc": "Полный запас заморозок",
     "cond": lambda s: s.get("freezes", 0) >= STREAK_FREEZE_MAX},
    {"id": "early_bird", "title": "Ранняя пташка", "icon": "goal",
     "desc": "Занятие до 7 утра",
     "cond": lambda s: s.get("hour", 12) < 7},
    {"id": "night_owl", "title": "Полуночник", "icon": "goal",
     "desc": "Занятие после 23:00",
     "cond": lambda s: s.get("hour", 12) >= 23},
]

ACHIEVEMENT_BY_ID = {a["id"]: a for a in ACHIEVEMENTS}


def earned_achievement_ids(stats: dict) -> set[str]:
    """Какие ачивки заслужены при данной статистике."""
    return {a["id"] for a in ACHIEVEMENTS if a["cond"](stats)}
