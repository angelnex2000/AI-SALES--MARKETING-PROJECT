import api from "@/lib/api";

/**
 * Integrations service (app/routers/integrations.py) — Admin only.
 *
 * Connecting is a real OAuth handshake: /connect returns a provider auth URL to
 * redirect to, and the backend exchanges the code and stores encrypted tokens.
 * The frontend never sees a token.
 */

export type IntegrationType = "crm" | "email" | "calendar" | "chat";
export type ConnectionStatus = "connected" | "disconnected" | "error";

export interface IntegrationDTO {
  id: string;
  integration_type: IntegrationType;
  provider: string;
  status: ConnectionStatus;
}

export const integrationsApi = {
  // No trailing slash — see the note in leadsApi.ts.
  list: async (): Promise<IntegrationDTO[]> => (await api.get<IntegrationDTO[]>("/integrations")).data,

  /** Returns the provider auth URL — the caller navigates to it. */
  connect: async (payload: { provider: string; integration_type: IntegrationType }): Promise<{ auth_url: string }> =>
    (await api.post<{ auth_url: string }>("/integrations/connect", payload)).data,

  disconnect: async (integrationId: string): Promise<void> => {
    await api.post(`/integrations/${integrationId}/disconnect`);
  },

  /** 202 + job_id — sync runs in the background. */
  sync: async (integrationId: string): Promise<{ job_id: string; status: string }> =>
    (await api.post<{ job_id: string; status: string }>(`/integrations/${integrationId}/sync`)).data,
};
