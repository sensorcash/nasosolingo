"""Проверка целостности контента курса «Водоснабжение» (30 уроков).

Ловит опечатки в seed-контенте до того, как их увидит пользователь:
недостающие поля, битые диапазоны, hotspots без верной зоны.
"""
import pytest

from content_water import WATER_UNITS

REQUIRED = {
    'mc':       ['prompt', 'options', 'answer', 'explain_ok'],
    'odd':      ['prompt', 'items', 'answer', 'explain_ok'],
    'order':    ['prompt', 'items', 'explain_ok'],
    'number':   ['prompt', 'answer', 'explain_ok'],
    'hotspots': ['prompt', 'image', 'spots', 'explain_ok'],
    'slider':   ['prompt', 'green_zone', 'explain_ok'],
    'match':    ['prompt', 'pairs', 'explain_ok'],
    'tap':      ['prompt', 'answer', 'explain_ok'],
    'sound':    ['prompt', 'audio', 'options', 'answer', 'explain_ok'],
}
CLIENT_TYPES = set(REQUIRED)

ALL_Q = [
    (u['slug'], l['slug'], q)
    for u in WATER_UNITS for l in u['lessons'] for q in l['content']['questions']
]


def test_thirty_lessons_present():
    lessons = [l for u in WATER_UNITS for l in u['lessons']]
    assert len(lessons) == 30


def test_six_units():
    assert len(WATER_UNITS) == 6


def test_unit_slugs_unique():
    slugs = [u['slug'] for u in WATER_UNITS]
    assert len(slugs) == len(set(slugs))


def test_lesson_slugs_unique_within_unit():
    for u in WATER_UNITS:
        slugs = [l['slug'] for l in u['lessons']]
        assert len(slugs) == len(set(slugs)), u['slug']


@pytest.mark.parametrize("unit,lesson,q", ALL_Q,
                         ids=[f"{u}/{l}/{q.get('id')}" for u, l, q in ALL_Q])
def test_question_contract(unit, lesson, q):
    t = q['type']
    assert t in CLIENT_TYPES, f"движок не умеет тип {t}"
    for field in REQUIRED[t]:
        assert field in q, f"нет поля {field}"

    if t in ('mc', 'sound'):
        assert 0 <= q['answer'] < len(q['options'])
        ee = q.get('explain_err', [])
        if ee:
            assert len(ee) == len(q['options'])
    elif t == 'odd':
        assert 0 <= q['answer'] < len(q['items'])
    elif t == 'order':
        assert len(q['items']) >= 2
    elif t == 'number':
        assert isinstance(q['answer'], (int, float))
        assert isinstance(q.get('tolerance', 0), (int, float))
    elif t == 'slider':
        gz = q['green_zone']
        assert len(gz) == 2 and 0 <= gz[0] < gz[1] <= 100
    elif t == 'hotspots':
        assert sum(1 for s in q['spots'] if s.get('correct')) == 1
        assert all('x' in s and 'y' in s for s in q['spots'])
    elif t == 'match':
        assert len(q['pairs']) >= 2
        assert all('left' in p and 'right' in p for p in q['pairs'])


def test_question_ids_unique_within_lesson():
    for u in WATER_UNITS:
        for l in u['lessons']:
            ids = [q['id'] for q in l['content']['questions']]
            assert len(ids) == len(set(ids)), f"{u['slug']}/{l['slug']}"
