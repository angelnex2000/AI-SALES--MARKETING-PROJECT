import api from "@/lib/api";

/**
 * Campaigns service (app/routers/campaigns.py). Marketing owns create/edit,
 * Manager approves, Admin is read-only. Templates are versioned — editing one
 * creates a new version row rather than mutating in place.
 */

export type CampaignStatus = "draft" | "active" | "paused" | "completed";

export interface CampaignDTO {
  id: string;
  name: string;
  description: string | null;
  target_industry: string | null;
  target_region: string | null;
  goal: string | null;
  status: CampaignStatus;
  start_date: string | null;
  end_date: string | null;
}

export interface TemplateDTO {
  id: string;
  name: string;
  subject: string;
  body: string;
  version: number;
  status: string;
}

export const campaignsApi = {
  // No trailing slash — see the note in leadsApi.ts.
  list: async (): Promise<CampaignDTO[]> => (await api.get<CampaignDTO[]>("/campaigns")).data,

  get: async (id: string): Promise<CampaignDTO> => (await api.get<CampaignDTO>(`/campaigns/${id}`)).data,

  approve: async (id: string): Promise<void> => {
    await api.post(`/campaigns/${id}/approve`);
  },

  listTemplates: async (): Promise<TemplateDTO[]> => (await api.get<TemplateDTO[]>("/campaigns/templates/all")).data,
};
