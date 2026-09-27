"use client";

import { AsyncBoundary, Panel } from "@/components/ui";
import { useApi, useMutation } from "@/hooks/useApi";
import { integrationsApi, type IntegrationType } from "@/lib/integrationsApi";

/**
 * The providers we support, mirroring the IntegrationProvider enum
 * (app/models/integration.py). GET /integrations only returns rows a tenant has
 * actually connected, so the catalog lives here and connection state is joined
 * onto it.
 */
const CATALOG: { provider: string; label: string; type: IntegrationType }[] = [
  { provider: "salesforce", label: "Salesforce", type: "crm" },
  { provider: "hubspot", label: "HubSpot", type: "crm" },
  { provider: "zoho", label: "Zoho", type: "crm" },
  { provider: "gmail", label: "Gmail", type: "email" },
  { provider: "google_calendar", label: "Google Calendar", type: "calendar" },
  { provider: "slack", label: "Slack", type: "chat" },
];

const TYPE_LABEL: Record<IntegrationType, string> = {
  crm: "CRM",
  email: "Email",
  calendar: "Calendar",
  chat: "Chat",
};

export default function IntegrationsPage() {
  // require_role(ADMIN) on every endpoint here.
  const { data, loading, error, refetch } = useApi(() => integrationsApi.list(), [], {
    fallbackError: "Failed to load integrations",
  });

  const connect = useMutation(integrationsApi.connect, "Could not start the connection");
  const disconnect = useMutation(integrationsApi.disconnect, "Could not disconnect");

  const connected = new Map((data ?? []).map((i) => [i.provider, i]));

  const onConnect = async (provider: string, integrationType: IntegrationType) => {
    const result = await connect.mutate({ provider, integration_type: integrationType });
    // The backend returns the provider's OAuth URL; the token exchange happens
    // server-side on the callback, so the frontend never handles a token.
    if (result?.auth_url) window.location.href = result.auth_url;
  };

  const onDisconnect = async (integrationId: string) => {
    if (await disconnect.mutate(integrationId)) refetch();
  };

  const actionError = connect.error ?? disconnect.error;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Integrations</h1>
        <p className="mt-1 text-sm text-gray-500">Connect your CRM, email, calendar, and chat tools.</p>
      </div>

      {actionError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{actionError}</div>
      )}

      <Panel>
        <AsyncBoundary loading={loading} error={error} loadingMessage="Loading integrations…">
          <div className="divide-y divide-gray-100">
            {CATALOG.map((item) => {
              const existing = connected.get(item.provider);
              const busy = connect.pending || disconnect.pending;
              return (
                <div key={item.provider} className="flex items-center justify-between py-3">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{item.label}</p>
                    <p className="text-xs text-gray-500">
                      {TYPE_LABEL[item.type]}
                      {existing?.status === "error" && " · connection error"}
                    </p>
                  </div>
                  {existing && existing.status !== "disconnected" ? (
                    <button
                      disabled={busy}
                      onClick={() => onDisconnect(existing.id)}
                      className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                    >
                      Disconnect
                    </button>
                  ) : (
                    <button
                      disabled={busy}
                      onClick={() => onConnect(item.provider, item.type)}
                      className="rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
                    >
                      Connect
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </AsyncBoundary>
      </Panel>
    </div>
  );
}
