"""
Pytest configuration and fixtures.
Provides an in-memory SQLite database session for unit tests.
"""

import asyncio
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jan_sahayak.database import Base


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Fixture that provides an in-memory SQLite database session.
    Automatically creates all tables before the test and drops them after.
    """
    # Use in-memory SQLite for speed and isolation
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Yield session
    async with session_factory() as session:
        yield session

    # Clean up
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator["httpx.AsyncClient", None]:
    """
    Fixture that provides an HTTP client connected to the FastAPI app with the test database.
    """
    import httpx

    from jan_sahayak.database import get_db
    from jan_sahayak.main import app

    # Override get_db dependency to use the in-memory test database session
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def auth_headers(db_session: AsyncSession) -> dict[str, str]:
    """Provides authorization headers for a test user."""
    from jan_sahayak.models.user import User
    from jan_sahayak.services.auth import create_access_token

    # Create dummy user
    user = User(
        phone="1234567890",
        name="Test User",
        preferred_language="hindi",
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}
