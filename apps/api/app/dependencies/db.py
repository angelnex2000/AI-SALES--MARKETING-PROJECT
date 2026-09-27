"""Request-scoped database session.

The rule from Module 4 holds: routers never construct a session or a
connection themselves, they declare `db: AsyncSession = Depends(get_db)`.
One session per request means the work of that request shares one
transaction and is cleaned up exactly once, whatever the outcome.
"""

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            # Explicit rollback before the connection returns to the pool.
            # `async with` would discard the transaction anyway, but being
            # explicit means a half-written multi-step service call can never
            # be observed by the next request to borrow this connection.
            await session.rollback()
            raise
