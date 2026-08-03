from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, pool_pre_ping=True, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
