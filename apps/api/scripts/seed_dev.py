"""Create and seed a local development database.

    DATABASE_URL="sqlite+aiosqlite:///./dev.db" python -m scripts.seed_dev

**This is not a substitute for Alembic and must never be pointed at Postgres.**
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "sqlite" not in os.environ.get("DATABASE_URL", ""):
    sys.exit(
        "Refusing to run: set DATABASE_URL to a sqlite+aiosqlite:// URL."
    )

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.core.security import hash_password  # noqa: E402

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
from app.models.lead import Contact, Lead, LeadStatus  # noqa: E402
from app.models.user import Role, User  # noqa: E402

PASSWORD = "DevPassw0rd!"

USERS = [
    ("admin@acmecorp.dev", "Asha Admin", Role.ADMIN),
    ("manager@acmecorp.dev", "Manoj Manager", Role.SALES_MANAGER),
    ("exec@acmecorp.dev", "Ravi Rep", Role.SALES_EXECUTIVE),
    ("marketing@acmecorp.dev", "Meera Marketing", Role.MARKETING),
]

LEADS = [
    ("ABC Healthcare", "Healthcare", "https://www.abchealthcare.com", "India", "Mumbai",
     1200, "webform", LeadStatus.NEW),
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
    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        existing = (await db.execute(select(Company).where(Company.name == "Acme Corp"))).scalar_one_or_none()
        if existing:
            # Add ABC Healthcare if missing
            lead_exists = (await db.execute(select(Lead).where(Lead.name == "ABC Healthcare"))).scalar_one_or_none()
            if not lead_exists:
                exec_user = (await db.execute(select(User).where(User.role == Role.SALES_EXECUTIVE))).scalars().first()
                new_lead = Lead(
                    company_id=existing.id,
                    name="ABC Healthcare",
                    industry="Healthcare",
                    website="https://www.abchealthcare.com",
                    country="India",
                    city="Mumbai",
                    employees=1200,
                    source="webform",
                    status=LeadStatus.NEW,
                    owner_id=exec_user.id if exec_user else None,
                )
                db.add(new_lead)
                await db.flush()
                db.add(
                    Contact(
                        company_id=existing.id,
                        lead_id=new_lead.id,
                        full_name="Rahul Sharma",
                        email="rahul.sharma@abchealthcare.com",
                        job_title="CTO",
                        is_primary=True,
                    )
                )
                await db.commit()
                print("Seeded ABC Healthcare with Contact Rahul Sharma (CTO) into dev.db!")
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

            contact_name = "Rahul Sharma" if name == "ABC Healthcare" else "Primary Contact"
            contact_title = "CTO" if name == "ABC Healthcare" else "Head of Operations"
            contact_email = "rahul.sharma@abchealthcare.com" if name == "ABC Healthcare" else f"contact@{name.split()[0].lower()}.dev"

            db.add(
                Contact(
                    company_id=company.id,
                    lead_id=lead.id,
                    full_name=contact_name,
                    email=contact_email,
                    job_title=contact_title,
                    is_primary=True,
                )
            )

        await db.commit()
        print("Successfully seeded Acme Corp with ABC Healthcare in dev.db")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
