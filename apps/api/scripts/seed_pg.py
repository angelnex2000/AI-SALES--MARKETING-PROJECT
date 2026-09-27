"""Seed Postgres development database after Alembic migrations have run.

Usage inside docker container or with DATABASE_URL set:
    python -m scripts.seed_pg
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.models.company import Company
from app.models.lead import Contact, Lead, LeadStatus
from app.models.user import Role, User

PASSWORD = "DevPassw0rd!"

USERS = [
    ("admin@acmecorp.dev", "Asha Admin", Role.ADMIN),
    ("manager@acmecorp.dev", "Manoj Manager", Role.SALES_MANAGER),
    ("exec@acmecorp.dev", "Ravi Rep", Role.SALES_EXECUTIVE),
    ("marketing@acmecorp.dev", "Meera Marketing", Role.MARKETING),
]

LEADS = [
    ("MedCare Hospital", "Healthcare", "https://www.apollohospitals.com", "India", "Chennai",
     4200, "referral", LeadStatus.NEW),
    ("Northwind Logistics", "Logistics", "https://www.dhl.com", "Germany", "Bonn",
     900, "cold_email", LeadStatus.RESEARCHING),
    ("Brightpath Learning", "Education", "https://www.byjus.com", "India", "Bengaluru",
     350, "webinar", LeadStatus.READY),
    ("Ferrovia Manufacturing", "Manufacturing", None, "Italy", "Turin",
     1800, "trade_show", LeadStatus.CONTACTED),
    ("Cobalt Fintech", "Financial Services", "https://www.stripe.com", "United States",
     "San Francisco", 210, "inbound", LeadStatus.NEW),
]


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/ai_sales")
    engine = create_async_engine(db_url, echo=False)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        existing = (await db.execute(select(Company).where(Company.name == "Acme Corp"))).scalar_one_or_none()
        if existing:
            print("Acme Corp already seeded in Postgres — leaving it alone.")
            await engine.dispose()
            return

        company = Company(name="Acme Corp")
        db.add(company)
        await db.flush()

        ids: dict[Role, object] = {}
        for email, full_name, role in USERS:
            user = User(
                company_id=company.id,
                email=email,
                hashed_password=hash_password(PASSWORD),
                full_name=full_name,
                role=role,
                is_active=True,
            )
            db.add(user)
            await db.flush()
            ids.setdefault(role, user.id)

        owner = ids[Role.SALES_EXECUTIVE]
        for name, industry, website, country, city, employees, source, status in LEADS:
            lead = Lead(
                company_id=company.id,
                name=name,
                industry=industry,
                website=website,
                country=country,
                city=city,
                employees=employees,
                source=source,
                status=status,
                owner_id=owner,
            )
            db.add(lead)
            await db.flush()
            db.add(
                Contact(
                    company_id=company.id,
                    lead_id=lead.id,
                    full_name="Primary Contact",
                    email=f"contact@{name.split()[0].lower()}.dev",
                    job_title="Head of Operations",
                    is_primary=True,
                )
            )

        await db.commit()

    await engine.dispose()
    print(f"Seeded Acme Corp: {len(USERS)} users, {len(LEADS)} leads.")
    print(f"Login credentials (password: {PASSWORD}):")
    for email, name, role in USERS:
        print(f"  - {role.value.upper()}: {email}")


if __name__ == "__main__":
    asyncio.run(main())
