from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    database_url: str = "postgresql+asyncpg://nasos:nasos@localhost:5432/nasos"
    redis_url: str = "redis://localhost:6379/0"

    # JWT / tokens
    jwt_secret: str = "dev-only-placeholder-change-in-prod-min-32-bytes"
    jwt_algorithm: str = "HS256"
    access_ttl_seconds: int = 15 * 60          # 15 минут
    refresh_ttl_seconds: int = 60 * 24 * 3600  # 60 дней

    # Argon2id (см. OWASP; подстроить под ~0.5с на своём железе)
    argon2_time_cost: int = 2
    argon2_memory_kib: int = 19456             # 19 MiB
    argon2_parallelism: int = 1

    # Политика пароля
    password_min_length: int = 10
    password_max_length: int = 128

    # Rate limits / локаут (см. auth-spec, раздел 6)
    login_max_fails: int = 5
    login_fail_window: int = 15 * 60
    login_ip_limit: int = 20
    lockout_base_seconds: int = 60
    lockout_cap_seconds: int = 3600

    register_ip_limit: int = 5
    register_window: int = 3600

    reset_email_limit: int = 3
    reset_ip_limit: int = 10
    reset_window: int = 3600
    reset_token_ttl: int = 30 * 60             # 30 минут
    verify_token_ttl: int = 7 * 24 * 3600      # 7 дней

    # Telegram Mini App: токен бота от @BotFather. Пусто → вход через Telegram выключен.
    telegram_bot_token: str = ""
    telegram_auth_max_age: int = 86400         # макс. возраст initData (защита от переигрывания)

    # Публичный адрес приложения — для ссылок в письмах
    public_base_url: str = "http://localhost:8000"

    # CORS: список доменов через запятую, или "*" для дева
    cors_origins: str = "*"

    # SMTP для писем. Пусто → письма логируются в консоль (как раньше).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""                         # адрес отправителя, напр. no-reply@example.ru
    smtp_from_name: str = "Насосолинго"
    smtp_use_tls: bool = True                   # STARTTLS (587); для 465 ставь False + smtp_ssl
    smtp_ssl: bool = False                      # прямой SSL (порт 465)

    # Аналитика: e-mail'ы с доступом к /admin, через запятую
    admin_emails: str = ""

    @property
    def cors_list(self) -> list[str]:
        v = self.cors_origins.strip()
        return ["*"] if v == "*" else [o.strip() for o in v.split(",") if o.strip()]

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


settings = Settings()
