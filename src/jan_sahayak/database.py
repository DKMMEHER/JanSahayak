"""
Database connection and session management.
Currently uses SQLite via aiosqlite for async support.
Can be switched to PostgreSQL later by changing DATABASE_URL in .env.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from jan_sahayak.config import get_settings

settings = get_settings()

# Create async engine
# SQLite: sqlite+aiosqlite:///./jan_sahayak.db
# PostgreSQL (later): postgresql+asyncpg://user:pass@localhost/jan_sahayak
engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,  # Log SQL queries in dev mode
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

# Session factory
async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


async def get_db() -> AsyncSession:
    """
    Dependency that provides a database session.
    Usage in FastAPI routes:
        async def my_route(db: AsyncSession = Depends(get_db)):
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all database tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close database connections on shutdown."""
    await engine.dispose()
