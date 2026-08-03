"""Генерация набора иконок интерфейса.

Единый стиль: сетка 24×24, толщина линии 2, скруглённые концы.
Цвет запечён в файл — так иконка работает и как <img>, и как фон.

Запуск:  .venv/bin/python tools/make_icons.py
Результат: web/img/icons/*.svg
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "web" / "img" / "icons"

# палитра приложения
AQUA, BRASS, DROP = "#10B0D6", "#E3A130", "#22A7E0"
SPRING, CORAL = "#38C173", "#F0603F"
INK, INK_SOFT, MUTED = "#0C3A4C", "#5C7C8A", "#B7CAD3"
WHITE, LOCK_GREY = "#FFFFFF", "#7C93A0"

S = 'fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
F = 'fill="{c}"'


def stroke(d, c, w=2):
    return f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>'


def fill(d, c):
    return f'<path d="{d}" fill="{c}"/>'


def circle(cx, cy, r, c, w=2, filled=False):
    if filled:
        return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{c}"/>'
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{c}" '
            f'stroke-width="{w}"/>')


ICONS = {
    # --- показатели ---
    "streak": (BRASS, "".join(
        stroke("M2 7c2-2.2 4-2.2 6 0s4 2.2 6 0 4-2.2 6 0", BRASS) for _ in [0]
    ) + stroke("M2 12c2-2.2 4-2.2 6 0s4 2.2 6 0 4-2.2 6 0", BRASS)
      + stroke("M2 17c2-2.2 4-2.2 6 0s4 2.2 6 0 4-2.2 6 0", BRASS)),

    "xp": (AQUA, fill("M13 2L5 14h6l-2 8 8-12h-6l2-8z", AQUA)),

    "life": (DROP, fill("M12 2.5s7 7.5 7 11.5a7 7 0 0 1-14 0c0-4 7-11.5 7-11.5z", DROP)),

    "life-empty": (MUTED, fill("M12 2.5s7 7.5 7 11.5a7 7 0 0 1-14 0c0-4 7-11.5 7-11.5z", MUTED)),

    "level": (BRASS, fill(
        "M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5-5.9-3.1-5.9 3.1 1.2-6.5L2.5 9.4l6.6-.9z", BRASS)),

    "goal": (BRASS, circle(12, 12, 9, BRASS) + circle(12, 12, 5, BRASS)
             + circle(12, 12, 1.6, BRASS, filled=True)),

    "accuracy": (BRASS, stroke("M6.5 17.5L17.5 6.5", BRASS)
                 + circle(8, 8, 2.6, BRASS) + circle(16, 16, 2.6, BRASS)),

    "time": (INK_SOFT, circle(12, 12, 9, INK_SOFT) + stroke("M12 6.5V12l4 2.5", INK_SOFT)),

    # --- узлы карты (белые: лежат на цветных кружках) ---
    "done": (WHITE, stroke("M4.5 12.5l5 5 10-11", WHITE, 2.8)),
    "current": (WHITE, fill("M12 2.5s7 7.5 7 11.5a7 7 0 0 1-14 0c0-4 7-11.5 7-11.5z", WHITE)),
    "locked": (LOCK_GREY, stroke("M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3", LOCK_GREY)
               + f'<rect x="5.5" y="10.5" width="13" height="9.5" rx="2.5" fill="{LOCK_GREY}"/>'),

    # --- обратная связь ---
    "ok": (SPRING, circle(12, 12, 9.2, SPRING) + stroke("M7.8 12.4l2.9 2.9 5.5-6", SPRING, 2.4)),
    "fail": (CORAL, circle(12, 12, 9.2, CORAL)
             + stroke("M8.6 8.6l6.8 6.8M15.4 8.6l-6.8 6.8", CORAL, 2.4)),
    "warn": (CORAL, stroke("M12 3.6L22 20.4H2z", CORAL) + stroke("M12 10v4", CORAL)
             + circle(12, 17.2, 1.1, CORAL, filled=True)),

    # --- навигация ---
    "close": (MUTED, stroke("M6.5 6.5l11 11M17.5 6.5l-11 11", MUTED, 2.4)),
    "back": (MUTED, stroke("M20 12H5M11 5.5L4.5 12l6.5 6.5", MUTED)),
    "arrow": (WHITE, stroke("M4 12h14M12.5 6l6 6-6 6", WHITE)),
    "menu": (INK_SOFT, stroke("M4 7h16M4 12h16M4 17h16", INK_SOFT)),

    # --- разделы и действия ---
    "review": (CORAL, stroke("M3.5 12a8.5 8.5 0 1 0 2.6-6.1", CORAL)
               + stroke("M2.6 2.4v4.2h4.2", CORAL)),
    "lesson": (AQUA, stroke(
        "M12 7.5C10.4 6 8 5.5 4 5.5v13c4 0 6.4.5 8 2 1.6-1.5 4-2 8-2v-13c-4 0-6.4.5-8 2z", AQUA)
        + stroke("M12 7.5v14", AQUA)),
    "user": (INK_SOFT, circle(12, 8, 3.8, INK_SOFT)
             + stroke("M4.8 20.5c1.4-3.9 3.9-5.8 7.2-5.8s5.8 1.9 7.2 5.8", INK_SOFT)),
    "export": (AQUA, stroke("M12 3.5v11.5M7.6 10.6L12 15l4.4-4.4M4 20h16", AQUA)),
    "logout": (INK_SOFT, stroke("M9.5 4.5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h3.5", INK_SOFT)
               + stroke("M15 8l4 4-4 4M19 12H9.5", INK_SOFT)),
    "delete": (CORAL, stroke("M4.5 6.5h15M9.5 6.5V4.2h5v2.3", CORAL)
               + stroke("M6.8 6.5l.9 13.3h8.6l.9-13.3", CORAL)
               + stroke("M10.3 10v6M13.7 10v6", CORAL)),
}


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (_color, body) in ICONS.items():
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
               f'width="24" height="24" role="img" aria-label="{name}">{body}</svg>')
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
    print(f"Готово: {len(ICONS)} иконок в {OUT}")
    return list(ICONS)


if __name__ == "__main__":
    build()
