"""Engine and session factory.

Async throughout — `create_async_engine` + asyncpg, not `create_engine` +
psycopg2. Every router in this app is `async def` and takes an
`AsyncSession`; a sync engine here would block the event loop on every
query and serialise the whole API behind one request at a time.

Nothing outside `dependencies/db.py` should build a session. Routers and
services receive one via `Depends(get_db)` so that a request's work shares a
single transaction and it is always closed.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.base import Base

# Pool tuning is Postgres-only. SQLite (used by the test suite via aiosqlite)
# has no server to pool against and rejects these arguments outright.
_pool_options: dict[str, Any] = {}
if not settings.DATABASE_URL.startswith("sqlite"):
    _pool_options = {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        # Verifies a connection is alive before handing it out. Without this,
        # the first request after a Postgres restart, a failover, or an idle
        # period behind a connection-killing proxy fails with a confusing
        # "server closed the connection unexpectedly".
        "pool_pre_ping": True,
        # Recycle below any upstream idle timeout (pgbouncer, cloud Postgres)
        # so we retire connections before the server does it for us.
        "pool_recycle": settings.DB_POOL_RECYCLE_SECONDS,
    }

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DB_ECHO, **_pool_options)

# expire_on_commit=False: after `await db.commit()` a service still needs to
# read the object it just wrote (to build a response). With the default True,
# every attribute access post-commit triggers a lazy refresh, which raises
# MissingGreenlet under async.
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

__all__ = ["Base", "engine", "AsyncSessionLocal"]
