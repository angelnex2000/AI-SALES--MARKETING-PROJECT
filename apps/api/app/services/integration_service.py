from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret
from app.models.integration import Integration, IntegrationSyncLog, SyncStatus


class CRMAdapter(ABC):
    """One adapter per CRM provider. The rest of the backend never talks to
    Salesforce/HubSpot/Zoho directly — everything routes through the Sync
    Manager (sync_leads below), which resolves a tenant's Integration to
    its adapter."""

    def __init__(self, integration: Integration):
        self.integration = integration
        self.access_token = (
            decrypt_secret(integration.access_token_encrypted)
            if integration.access_token_encrypted
            else None
        )

    @abstractmethod
    async def pull_leads(self) -> list[dict[str, Any]]:
        """Fetch leads/contacts/companies from the external CRM."""
        ...

    @abstractmethod
    async def push_activity(self, *, external_crm_id: str, activity: dict[str, Any]) -> None:
        """Push a locally-generated event (meeting scheduled, email sent,
        status change) back to the external CRM."""
        ...


class SalesforceAdapter(CRMAdapter):
    async def pull_leads(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Salesforce API client not yet wired up")

    async def push_activity(self, *, external_crm_id: str, activity: dict[str, Any]) -> None:
        raise NotImplementedError("Salesforce API client not yet wired up")


class HubSpotAdapter(CRMAdapter):
    async def pull_leads(self) -> list[dict[str, Any]]:
        raise NotImplementedError("HubSpot API client not yet wired up")

    async def push_activity(self, *, external_crm_id: str, activity: dict[str, Any]) -> None:
        raise NotImplementedError("HubSpot API client not yet wired up")


class ZohoAdapter(CRMAdapter):
    async def pull_leads(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Zoho API client not yet wired up")

    async def push_activity(self, *, external_crm_id: str, activity: dict[str, Any]) -> None:
        raise NotImplementedError("Zoho API client not yet wired up")


ADAPTERS: dict[str, type[CRMAdapter]] = {
    "salesforce": SalesforceAdapter,
    "hubspot": HubSpotAdapter,
    "zoho": ZohoAdapter,
}


async def sync_leads(db: AsyncSession, *, integration: Integration) -> IntegrationSyncLog:
    """Sync Manager entry point. If the CRM is unavailable or the adapter
    isn't implemented yet, the failure is recorded here rather than raised
    to the caller — retry is a scheduled job's job, not this call's."""

    adapter_cls = ADAPTERS[integration.provider.value]
    adapter = adapter_cls(integration)

    try:
        await adapter.pull_leads()
        log = IntegrationSyncLog(
            company_id=integration.company_id,
            integration_id=integration.id,
            sync_type="lead_import",
            status=SyncStatus.SUCCESS,
        )
    except Exception as exc:  # noqa: BLE001 — captured in the log, not swallowed
        log = IntegrationSyncLog(
            company_id=integration.company_id,
            integration_id=integration.id,
            sync_type="lead_import",
            status=SyncStatus.FAILED,
            error_message=str(exc),
        )

    db.add(log)
    await db.commit()
    return log