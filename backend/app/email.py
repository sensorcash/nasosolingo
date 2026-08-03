"""Отправка писем.

Если SMTP настроен в .env (smtp_host + smtp_from) — письма уходят по-настоящему.
Если нет — ссылка логируется в консоль, как в деве. Так одно и то же приложение
работает и локально без почты, и в проде с реальными письмами.

Отправка синхронная, но вызывается в фоне (BackgroundTasks) уже ПОСЛЕ commit —
пользователь не ждёт SMTP, и медленная почта не роняет запрос.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.config import settings

log = logging.getLogger("email")


def _links(token: str, kind: str) -> str:
    base = settings.public_base_url.rstrip("/")
    return f"{base}/app?{kind}={token}"


def _send(to: str, subject: str, text: str, html: str) -> None:
    """Отправить письмо. Без настроенного SMTP — залогировать и выйти."""
    if not settings.smtp_configured:
        log.warning("[EMAIL STUB] %s -> %s | %s", subject, to, text.replace("\n", " ")[:200])
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.smtp_from_name, settings.smtp_from))
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    try:
        if settings.smtp_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=15) as s:
                _login_send(s, msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
                if settings.smtp_use_tls:
                    s.starttls(context=ssl.create_default_context())
                _login_send(s, msg)
        log.info("Письмо отправлено: %s -> %s", subject, to)
    except Exception:                       # noqa: BLE001 — письмо не должно ронять запрос
        log.exception("Не удалось отправить письмо на %s", to)


def _login_send(s: smtplib.SMTP, msg: EmailMessage) -> None:
    if settings.smtp_user:
        s.login(settings.smtp_user, settings.smtp_password)
    s.send_message(msg)


def _wrap(title: str, body: str, button_text: str, url: str) -> tuple[str, str]:
    text = f"{title}\n\n{body}\n\n{url}\n\nЕсли вы не запрашивали это письмо, просто проигнорируйте его."
    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:480px;margin:0 auto;color:#0C3A4C">
  <h2 style="color:#10B0D6">Насосолинго</h2>
  <p style="font-size:16px;font-weight:700">{title}</p>
  <p style="font-size:14px;line-height:1.5">{body}</p>
  <p><a href="{url}" style="display:inline-block;background:#10B0D6;color:#fff;text-decoration:none;
     padding:12px 22px;border-radius:12px;font-weight:700">{button_text}</a></p>
  <p style="font-size:12px;color:#5C7C8A">Если вы не запрашивали это письмо, просто проигнорируйте его.</p>
</div>"""
    return text, html


def send_password_reset(email: str, token: str) -> None:
    url = _links(token, "reset")
    text, html = _wrap("Сброс пароля",
                       "Вы запросили сброс пароля. Ссылка действует 30 минут.",
                       "Сбросить пароль", url)
    _send(email, "Сброс пароля — Насосолинго", text, html)


def send_email_verification(email: str, token: str) -> None:
    url = _links(token, "verify")
    text, html = _wrap("Подтверждение e-mail",
                       "Подтвердите адрес, чтобы восстановить пароль в будущем.",
                       "Подтвердить e-mail", url)
    _send(email, "Подтверждение e-mail — Насосолинго", text, html)
