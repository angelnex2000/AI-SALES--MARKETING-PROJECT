import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditCategory, AuditLog


async def log_action(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    category: AuditCategory = AuditCategory.BUSINESS,
    details: dict[str, Any] | None = None,
) -> None:
    """Single entry point for audit logging — every RBAC-sensitive action
    (lead assignment, role change, integration credential update, failed
    login) should call this rather than writing to AuditLog directly, so
    the shape stays consistent."""

    db.add(
        AuditLog(
            company_id=company_id,
            actor_id=actor_id,
            category=category,
            action=action,
            details=details,
        )
    )
    await db.commit()