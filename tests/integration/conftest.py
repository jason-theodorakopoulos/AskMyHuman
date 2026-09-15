from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from ask_my_human.persistence.pool import PostgresPool
from ask_my_human.persistence.repository import PostgresRequestRepository


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        config = Config("alembic.ini")
        migration_url = url.replace("postgresql+psycopg2", "postgresql+psycopg")
        config.set_main_option("sqlalchemy.url", migration_url)
        command.upgrade(config, "head")
        yield migration_url


@pytest_asyncio.fixture
async def postgres_pool(database_url: str) -> AsyncIterator[PostgresPool]:
    pool = PostgresPool(database_url, min_size=1, max_size=8)
    await pool.open()
    try:
        async with pool.pool.connection() as connection:
            await connection.execute("TRUNCATE human_requests")
        yield pool
    finally:
        await pool.close()


@pytest.fixture
def repository(postgres_pool: PostgresPool) -> PostgresRequestRepository:
    return PostgresRequestRepository(postgres_pool.pool)
