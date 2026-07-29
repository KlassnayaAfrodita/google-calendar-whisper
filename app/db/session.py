"""Асинхронный SQLAlchemy engine и session factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import unquote, urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """Create SQLite parent directory before SQLAlchemy opens the database."""
    if not database_url.startswith("sqlite"):
        return

    parsed = urlparse(database_url)
    db_path = unquote(parsed.path)
    if parsed.netloc:
        db_path = f"//{parsed.netloc}{db_path}"

    if not db_path or db_path in {":memory:", "/:memory:"}:
        return

    Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent_dir(settings.database_url)

engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level == "DEBUG",
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Создать все таблицы (для разработки). В проде — Alembic."""
    from app.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Зависимость для получения сессии БД."""
    async with async_session_factory() as session:
        yield session
