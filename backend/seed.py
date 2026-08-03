"""Наполнение базы стартовым контентом.

Запуск:  .venv\\Scripts\\python seed.py     (Windows)
         .venv/bin/python seed.py          (Mac/Linux)

Скрипт идемпотентный: повторный запуск обновит контент, а не создаст дубли.
Именно так контент и должен приезжать — данными, без релиза приложения.
"""
import asyncio
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.game.models import Course, Lesson, Unit
from content_water import WATER_UNITS

COURSE = {"slug": "water-supply", "title": "Водоснабжение", "order": 1}

UNITS = [
    {"slug": "basics", "title": "Азы", "order": 1},
    {"slug": "install", "title": "Монтаж скважинного", "order": 3},
    {"slug": "formats", "title": "Разные форматы", "order": 4},
]

# Тот самый урок из прототипа, теперь — данные, а не код.
INSTALL_LESSON = {
    "slug": "pump-placement",
    "title": "Установка насоса",
    "order": 1,
    "content": {
        "mascot": "triton-3363",
        "questions": [
            {
                "id": "q1",
                "type": "mc",
                "kicker": "Правило глубины",
                "prompt": "На какой глубине должен висеть скважинный насос?",
                "options": [
                    "На самом дне — чтобы забирать максимум воды",
                    "Ниже динамического уровня, но на 1–2 м выше дна",
                    "У оголовка — чтобы проще было доставать",
                ],
                "answer": 1,
                "explain_ok": "Верно! Ниже динамического уровня — насос всегда в воде. "
                              "И на 1–2 м выше дна — чтобы не хватать песок.",
                "explain_err": [
                    "На дне насос всасывает песок и ил — крыльчатка стачивается за сезон.",
                    "",
                    "У оголовка насос окажется выше воды — сухой ход и перегрев.",
                ],
            },
            {
                "id": "q2",
                "type": "tap",
                "kicker": "Найди ошибку",
                "prompt": "Монтаж с браком. Тапни то, из-за чего насос сгорит.",
                "scene": "dryrun",
                "hotspots": ["pump", "level", "head"],
                "answer": "pump",
                "hint": "Подсказка: посмотри, где уровень воды.",
                "explain_ok": "Точно! Насос висит выше динамического уровня — работает всухую "
                              "и выходит из строя.",
                "explain_err": "Смотри на уровень воды: насос висит в воздухе, выше "
                               "динамического уровня. Это и есть сухой ход.",
            },
            {
                "id": "q3",
                "type": "slider",
                "kicker": "Поставь правильно",
                "prompt": "Опусти насос в рабочую зону.",
                "scene": "well",
                "green_zone": [42, 82],
                "hint": "Тяни ползунок. Зелёная зона — в воде и выше дна.",
                "explain_ok": "Идеально. Насос полностью в воде и не достаёт до дна.",
                "explain_low": "Насос выше динамического уровня — сухой ход и перегрев.",
                "explain_high": "Слишком низко — насос достаёт до дна и хватает песок.",
            },
            {
                "id": "q4",
                "type": "match",
                "kicker": "Симптом → причина",
                "prompt": "Свяжи неисправность с причиной.",
                "pairs": [
                    {"left": "Гудит, но не качает", "right": "Сухой ход / завоздушивание"},
                    {"left": "В воде песок, быстрый износ", "right": "Насос висит слишком низко"},
                    {"left": "Частые вкл/выкл", "right": "Мало воздуха в гидробаке"},
                ],
                "explain_ok": "Связал верно! Симптом → причина — это половина ремонта.",
            },
            {
                "id": "q5",
                "type": "mc",
                "kicker": "Подбор по объекту",
                "prompt": "Какой минимальный напор нужен насосу?",
                "scenario": "Скважина 50 м. Динамический уровень 32 м. "
                            "Дом 2 этажа (+8 м). На выходе нужно 3 атм (≈ 30 м).",
                "options": ["40 м", "60 м", "80 м"],
                "answer": 2,
                "explain_ok": "Верно! 32 + 8 + 30 ≈ 70 м, плюс запас на потери → берём ~80 м.",
                "explain_err": [
                    "Мало. Один динамический уровень уже 32 м.",
                    "Впритык и без запаса: на верхнем этаже давления не будет.",
                    "",
                ],
            },
        ],
    },
}

# Демонстрация новых типов заданий (не только выбор варианта).
FORMATS_LESSON = {
    "slug": "formats-demo",
    "title": "Разные форматы",
    "order": 1,
    "content": {
        "mascot": "triton-3363",
        "questions": [
            {
                "id": "f1",
                "type": "odd",
                "kicker": "Что лишнее",
                "prompt": "Что здесь не относится к скважинному насосу?",
                "items": ["Крыльчатка", "Обратный клапан", "Дымоход", "Кабель"],
                "answer": 2,
                "explain_ok": "Верно! Дымоход — из другой оперы. Остальное есть у скважинного насоса.",
                "explain_err": "Лишний — дымоход. Он к насосам отношения не имеет.",
            },
            {
                "id": "f2",
                "type": "order",
                "kicker": "По порядку",
                "prompt": "Расставь монтаж по шагам — от скважины к дому.",
                "hint": "Первым делом — насос, последним — гидробак у дома.",
                "items": [
                    "Опустить насос в скважину",
                    "Присоединить обратный клапан",
                    "Проложить трубу до дома",
                    "Поставить гидроаккумулятор",
                ],
                "explain_ok": "Точно! Именно в таком порядке и монтируют.",
                "explain_err": "Порядок другой: сверху вниз по списку.",
            },
            {
                "id": "f3",
                "type": "number",
                "kicker": "Посчитай напор",
                "prompt": "Динамический уровень 32 м, дом +8 м, 3 атм (≈30 м). Сколько метров напора нужно минимум?",
                "unit": "м",
                "answer": 70,
                "tolerance": 2,
                "hint": "Сложи три числа.",
                "explain_ok": "Верно! 32 + 8 + 30 = 70 м. На практике берут с запасом, ~80 м.",
                "explain_err": "Сложи: 32 + 8 + 30 = 70 м.",
            },
            {
                "id": "f4",
                "type": "hotspots",
                "kicker": "Найди на схеме",
                "prompt": "Где на этой схеме обратный клапан?",
                "image": "pump-types.jpg",
                "image_alt": "Схема с погружным насосом",
                "hint": "Он сразу над насосом.",
                "spots": [
                    {"x": 25, "y": 78, "r": 9, "label": "насос", "correct": False},
                    {"x": 25, "y": 55, "r": 9, "label": "обратный клапан", "correct": True},
                    {"x": 72, "y": 45, "r": 9, "label": "поверхностный", "correct": False},
                ],
                "explain_ok": "Да, обратный клапан ставят сразу над насосом.",
                "explain_err": "Клапан — прямо над насосом, чтобы держать столб воды.",
            },
        ],
    },
}


BASICS_LESSON = {
    "slug": "pump-types",
    "title": "Типы насосов",
    "order": 1,
    "content": {
        "mascot": "triton-3363",
        "questions": [
            {
                "id": "q1",
                "type": "mc",
                "kicker": "Термины",
                "prompt": "Какой насос опускают прямо в скважину?",
                # Картинка лежит в web/img/ и подключается коротким именем.
                # Можно указать и полный путь: "/static/img/…" или внешний URL.
                "image": "pump-types.jpg",
                "image_alt": "Слева погружной насос в скважине, справа поверхностный",
                "image_caption": "Слева — под водой, справа — снаружи",
                "options": ["Поверхностный", "Погружной (скважинный)", "Циркуляционный"],
                "answer": 1,
                "explain_ok": "Верно. Погружной работает под водой, она же его и охлаждает.",
                "explain_err": [
                    "Поверхностный стоит снаружи и всасывает воду — глубина ограничена.",
                    "",
                    "Циркуляционный гоняет воду по контуру отопления, а не поднимает из скважины.",
                ],
            },
            {
                "id": "q2",
                "type": "mc",
                "kicker": "Термины",
                "prompt": "Что такое динамический уровень?",
                "options": [
                    "Уровень воды в покое",
                    "Уровень воды при работающем насосе",
                    "Глубина скважины до дна",
                ],
                "answer": 1,
                "explain_ok": "Да. При откачке уровень опускается — именно от него считают подвес.",
                "explain_err": [
                    "Это статический уровень — вода в покое.",
                    "",
                    "Это глубина скважины, а уровень воды всегда выше дна.",
                ],
            },
        ],
    },
}


async def upsert_lesson(session, unit_id: uuid.UUID, data: dict) -> None:
    lesson = await session.scalar(
        select(Lesson).where(Lesson.unit_id == unit_id, Lesson.slug == data["slug"])
    )
    qcount = len(data["content"]["questions"])
    if lesson is None:
        session.add(Lesson(
            unit_id=unit_id, slug=data["slug"], title=data["title"], order=data["order"],
            content=data["content"], question_count=qcount, version=1,
        ))
        print(f"  + урок «{data['title']}» ({qcount} вопросов)")
    else:
        lesson.title = data["title"]
        lesson.content = data["content"]
        lesson.question_count = qcount
        lesson.version += 1                    # версия растёт → клиент перекачает контент
        print(f"  ~ урок «{data['title']}» обновлён (версия {lesson.version})")


async def main() -> None:
    async with SessionLocal() as session:
        course = await session.scalar(select(Course).where(Course.slug == COURSE["slug"]))
        if course is None:
            course = Course(**COURSE)
            session.add(course)
            await session.flush()
            print(f"+ курс «{course.title}»")
        else:
            print(f"~ курс «{course.title}» уже есть")

        units = {}
        for u in UNITS:
            unit = await session.scalar(
                select(Unit).where(Unit.course_id == course.id, Unit.slug == u["slug"])
            )
            if unit is None:
                unit = Unit(course_id=course.id, **u)
                session.add(unit)
                await session.flush()
                print(f"+ юнит «{unit.title}»")
            units[u["slug"]] = unit

        await upsert_lesson(session, units["basics"].id, BASICS_LESSON)
        await upsert_lesson(session, units["install"].id, INSTALL_LESSON)
        await upsert_lesson(session, units["formats"].id, FORMATS_LESSON)

        # --- основной курс: 30 уроков по водоснабжению (content_water.py) ---
        for u in WATER_UNITS:
            unit = await session.scalar(
                select(Unit).where(Unit.course_id == course.id, Unit.slug == u["slug"])
            )
            if unit is None:
                unit = Unit(course_id=course.id, slug=u["slug"],
                            title=u["title"], order=u["order"])
                session.add(unit)
                await session.flush()
                print(f"+ юнит «{unit.title}»")
            for lesson_data in u["lessons"]:
                await upsert_lesson(session, unit.id, lesson_data)

        await session.commit()
        print("\nГотово. Контент загружен в базу.")


if __name__ == "__main__":
    asyncio.run(main())
