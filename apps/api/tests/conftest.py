"""Shared test fixtures.

Tests run against a real SQLite database, not mocks: the rules being tested
(tenant isolation, assigned-only visibility, state machines) are enforced in
SQL `WHERE` clauses, so a mocked session would prove nothing.

The whole schema builds on SQLite because `JSONColumn` and the `Vector`
column both declare SQLite variants (`app/models/base.py`). Two things still
require real Postgres and are marked `@pytest.mark.postgres`:
  * pgvector similarity search (no `<=>` operator in SQLite)
  * anything asserting on Postgres ENUM type behaviour
"""

import os
import uuid
from collections.abc import AsyncIterator, Iterator

# Environment must be set before app modules import, because core/config.py
# builds its Settings at import time.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "testing-only-secret-key-long-enough-32")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:65530/0")

# No test may reach a third-party provider. Set, not `setdefault`: `config.py`
# reads `apps/api/.env`, so a developer with working keys would otherwise have
# the suite quietly calling OpenAI, TinyFish and Mailjet on every run — slow,
# flaky, billable, and in the case of `EMAIL_SEND_ENABLED` capable of sending
# real mail to a seeded contact address.
#
# Tests that exercise these paths patch the settings object directly (see
# `test_research_web.py::configured`, `test_email_delivery.py::live`), which is
# also what keeps them honest about which provider behaviour they are assuming.
for _external in (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "TINYFISH_API_KEY",
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "EMAIL_FROM_ADDRESS",
):
    os.environ[_external] = ""
os.environ["EMAIL_SEND_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.dependencies.db import get_db  # noqa: E402
from app.main import app  # noqa: E402

# Every model module must be imported so Base.metadata is complete before
# create_all. Written as `from app.models import x` rather than
# `import app.models.x` on purpose — the latter rebinds the name `app` to the
# package and clobbers the FastAPI instance imported above.
from app.models import (  # noqa: E402,F401
    ai_log,
    audit_log,
    billing,
    campaign,
    crm,
    deal,
    feedback,
    forecast,
    integration,
    job,
    knowledge,
    meeting,
    model_registry,
    outreach,
)
from app.models.company import Company  # noqa: E402
from app.models.lead import Contact, Lead  # noqa: E402
from app.models.user import Role, User  # noqa: E402

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def engine() -> AsyncIterator:
    """A fresh in-memory database per test.

    Isolation and state-machine tests mutate rows, so sharing one database
    across tests would let ordering decide outcomes. In-memory + StaticPool
    keeps that isolation while avoiding the file I/O of creating 33 tables per
    test — the same suite took ~5.5 minutes against a file database and ~40
    seconds here. StaticPool is required: each new connection to
    `:memory:` would otherwise get its own empty database.
    """

    eng = create_async_engine(TEST_DB_URL, echo=False, poolclass=StaticPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session_factory(engine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
async def db(session_factory) -> AsyncIterator[AsyncSession]:
    """Direct session for seeding and for asserting on stored rows."""

    async with session_factory() as session:
        yield session


@pytest.fixture
def client(session_factory) -> Iterator[TestClient]:
    """TestClient with get_db overridden onto the test database.

    The override mirrors the real dependency including its rollback-on-error
    behaviour, so tests exercise the same session lifecycle as production.
    """

    async def _override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --------------------------------------------------------------------- data


class Tenant:
    """One seeded company with a user per role, a lead, and a contact.

    Attributes are plain ids so tests read as `tenant.exec_id`, and `headers()`
    produces an auth header for any seeded role.
    """

    def __init__(self, company_id: uuid.UUID, users: dict[str, uuid.UUID]):
        self.company_id = company_id
        self.users = users
        self.lead_id: uuid.UUID | None = None
        self.contact_id: uuid.UUID | None = None

    @property
    def admin_id(self) -> uuid.UUID:
        return self.users["admin"]

    @property
    def manager_id(self) -> uuid.UUID:
        return self.users["sales_manager"]

    @property
    def exec_id(self) -> uuid.UUID:
        return self.users["sales_executive"]

    @property
    def exec2_id(self) -> uuid.UUID:
        return self.users["sales_executive_2"]

    @property
    def marketing_id(self) -> uuid.UUID:
        return self.users["marketing"]

    def headers(self, role: str) -> dict[str, str]:
        key = role if role in self.users else role
        token = create_access_token(
            user_id=self.users[key],
            company_id=self.company_id,
            role="sales_executive" if key == "sales_executive_2" else key,
        )
        return {"Authorization": f"Bearer {token}"}


async def seed_tenant(db: AsyncSession, name: str = "Acme") -> Tenant:
    company = Company(name=name)
    db.add(company)
    await db.flush()

    users: dict[str, uuid.UUID] = {}
    for key, role in (
        ("admin", Role.ADMIN),
        ("sales_manager", Role.SALES_MANAGER),
        ("sales_executive", Role.SALES_EXECUTIVE),
        ("sales_executive_2", Role.SALES_EXECUTIVE),
        ("marketing", Role.MARKETING),
    ):
        user = User(
            company_id=company.id,
            email=f"{name.lower()}-{key}@example.com",
            hashed_password="not-a-real-hash",
            full_name=f"{name} {key}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        users[key] = user.id

    tenant = Tenant(company.id, users)

    lead = Lead(company_id=company.id, name=f"{name} Prospect", owner_id=users["sales_executive"])
    db.add(lead)
    await db.flush()
    tenant.lead_id = lead.id

    contact = Contact(
        company_id=company.id,
        lead_id=lead.id,
        full_name="Primary Person",
        # An address, because send_draft now refuses a contact without one.
        email=f"primary@{name.lower()}.example.com",
        is_primary=True,
    )
    db.add(contact)
    await db.flush()
    tenant.contact_id = contact.id

    await db.commit()
    return tenant


@pytest.fixture
async def tenant(db) -> Tenant:
    return await seed_tenant(db, "Acme")


@pytest.fixture
async def other_tenant(db) -> Tenant:
    """A second company, for proving cross-tenant requests get 404."""

    return await seed_tenant(db, "Rival")
