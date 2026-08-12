import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import get_session
from app.auth.router import router as auth_router
from app.game.router import router as game_router
from app.admin.router import router as admin_router
from app.errors import install_error_handlers

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """При старте (если задан токен бота) поднимаем фоновые задачи Telegram:
    приём /start и ежедневные напоминания. При остановке — гасим их."""
    tasks = []
    stop = asyncio.Event()
    if settings.telegram_bot_token:
        from app import bot
        tasks = [asyncio.create_task(bot.run_polling(stop)),
                 asyncio.create_task(bot.run_reminders(stop))]
    try:
        yield
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


app = FastAPI(title="Насосолинго — API", version="0.2.0", lifespan=lifespan)
install_error_handlers(app)
app.include_router(auth_router)
app.include_router(game_router)
app.include_router(admin_router)

# Разрешаем запросы с других адресов — нужно, если клиент открыт не с этого же
# сервера (например, из отдельного дев-сервера).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Клиент раздаётся тем же сервером: один адрес и для ПК, и для телефона,
# и никаких проблем с разными источниками.
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/app", include_in_schema=False)
    async def client_app():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/icons", include_in_schema=False)
    async def icons_page():
        """Каталог иконок: видно все разом и понятно, какой файл менять."""
        return FileResponse(WEB_DIR / "icons.html")

    @app.get("/admin", include_in_schema=False)
    async def admin_page():
        """Дашборд аналитики. Данные тянет с токеном из localStorage (нужен админ)."""
        return FileResponse(WEB_DIR / "admin.html")


@app.get("/health", tags=["system"])
async def health(session=Depends(get_session)):
    """Проверка живости для мониторинга и балансировщика.

    Возвращает 503, если недоступна база или Redis — тогда мониторинг это увидит,
    а балансировщик перестанет слать трафик на битый инстанс.
    """
    from fastapi.responses import JSONResponse
    from sqlalchemy import text
    from app.redis_client import redis

    checks = {"db": False, "redis": False}
    try:
        await session.execute(text("SELECT 1"))
        checks["db"] = True
    except Exception:
        pass
    try:
        await redis.ping()
        checks["redis"] = True
    except Exception:
        pass

    healthy = all(checks.values())
    body = {"status": "ok" if healthy else "degraded", "checks": checks}
    return body if healthy else JSONResponse(body, status_code=503)
