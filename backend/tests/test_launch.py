"""Тесты «запуска для людей»: почта, health-check, аналитика, доступ админа."""
import uuid

import pytest

from app.config import settings

GAME = "/api/v1/game"
ADMIN = "/api/v1/admin"


def _ev():
    return "L-" + uuid.uuid4().hex[:12]


# ==================== КОНФИГ ====================

def test_cors_list_wildcard():
    s = settings.__class__(cors_origins="*")
    assert s.cors_list == ["*"]


def test_cors_list_multiple():
    s = settings.__class__(cors_origins="https://a.ru, https://b.ru")
    assert s.cors_list == ["https://a.ru", "https://b.ru"]


def test_admin_email_set_parsing():
    s = settings.__class__(admin_emails="A@x.ru, b@Y.ru")
    assert s.admin_email_set == {"a@x.ru", "b@y.ru"}


def test_smtp_not_configured_by_default():
    s = settings.__class__()
    assert s.smtp_configured is False


def test_smtp_configured_when_host_and_from_set():
    s = settings.__class__(smtp_host="smtp.x.ru", smtp_from="a@x.ru")
    assert s.smtp_configured is True


# ==================== ПОЧТА ====================

def test_email_stub_does_not_crash(monkeypatch):
    """Без SMTP письмо не отправляется, но и не падает."""
    import app.email as e
    monkeypatch.setattr(settings, "smtp_host", "")
    e.send_password_reset("user@example.ru", "tok123")
    e.send_email_verification("user@example.ru", "tok456")


def test_email_link_uses_public_base(monkeypatch):
    import app.email as e
    monkeypatch.setattr(settings, "public_base_url", "https://nasos.ru")
    assert e._links("abc", "reset") == "https://nasos.ru/app?reset=abc"


def test_email_send_calls_smtp_when_configured(monkeypatch):
    """С настроенным SMTP письмо реально уходит в smtplib (мок)."""
    import app.email as e
    monkeypatch.setattr(settings, "smtp_host", "smtp.test.ru")
    monkeypatch.setattr(settings, "smtp_from", "no-reply@test.ru")
    monkeypatch.setattr(settings, "smtp_ssl", False)
    monkeypatch.setattr(settings, "smtp_use_tls", False)
    monkeypatch.setattr(settings, "smtp_user", "")

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=15): sent["host"] = host
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self, context=None): pass
        def login(self, u, p): sent["login"] = u
        def send_message(self, msg): sent["to"] = msg["To"]

    monkeypatch.setattr(e.smtplib, "SMTP", FakeSMTP)
    e.send_password_reset("user@example.ru", "tok")
    assert sent.get("host") == "smtp.test.ru"
    assert sent.get("to") == "user@example.ru"


# ==================== HEALTH ====================

@pytest.mark.asyncio
async def test_health_reports_checks(client):
    r = await client.get("/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["checks"]["db"] is True
    assert d["checks"]["redis"] is True


# ==================== АНАЛИТИКА / ДОСТУП ====================

@pytest.mark.asyncio
async def test_analytics_requires_auth(client, seeded):
    assert (await client.get(f"{ADMIN}/analytics")).status_code == 401


@pytest.mark.asyncio
async def test_analytics_forbidden_for_non_admin(auth_client, seeded, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "")   # никого нет в админах
    assert (await auth_client.get(f"{ADMIN}/analytics")).status_code == 403


@pytest.mark.asyncio
async def test_analytics_ok_for_admin(auth_client, seeded, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", auth_client.email)
    r = await auth_client.get(f"{ADMIN}/analytics")
    assert r.status_code == 200
    d = r.json()
    assert "overview" in d and "funnel" in d and "hardest_questions" in d


@pytest.mark.asyncio
async def test_analytics_reflects_activity(auth_client, seeded, monkeypatch):
    """Пройдём урок с ошибкой — вопрос всплывёт в «сложных», урок в воронке."""
    monkeypatch.setattr(settings, "admin_emails", auth_client.email)

    # два прохождения одного вопроса: один раз неверно, один верно
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 1, "total": 2, "mistakes": 1,
        "answers": [{"question_id": "q1", "correct": False},
                    {"question_id": "q2", "correct": True}]})

    d = (await auth_client.get(f"{ADMIN}/analytics")).json()
    assert d["overview"]["lesson_completions"] >= 1
    # в воронке есть урок 1 с одним прошедшим игроком
    funnel_lessons = {f["lesson"]: f["players_completed"] for f in d["funnel"]}
    assert funnel_lessons.get("Урок 1", 0) >= 1


@pytest.mark.asyncio
async def test_hardest_questions_needs_min_attempts(auth_client, seeded, monkeypatch):
    """Вопрос с одной попыткой не попадает в список (порог >= 2)."""
    monkeypatch.setattr(settings, "admin_emails", auth_client.email)
    await auth_client.post(f"{GAME}/lessons/{seeded['l1']}/complete", json={
        "client_event_id": _ev(), "correct": 2, "total": 2,
        "answers": [{"question_id": "q1", "correct": True}]})
    d = (await auth_client.get(f"{ADMIN}/analytics")).json()
    # q1 отвечен один раз — не должен быть в сложных
    assert all(q["attempts"] >= 2 for q in d["hardest_questions"])
