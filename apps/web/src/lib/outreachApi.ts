import api from "@/lib/api";

/**
 * Outreach service (app/routers/outreach.py) — Gate 2 lives here.
 *
 * approve/reject/send are `require_role(Role.SALES_EXECUTIVE)` and additionally
 * scoped to the assigned lead: Admin can never send, Marketing can only draft.
 * The UI hides the buttons; this is not where the rule is enforced.
 */

export type DraftStatus = "pending_approval" | "approved" | "rejected" | "sent";

export interface DraftDTO {
  id: string;
  lead_id: string;
  contact_id: string | null;
  campaign_id: string | null;
  subject: string;
  body: string;
  ai_generated: boolean;
  explanation: string;
  status: DraftStatus;
}

export interface SentEmailDTO {
  id: string;
  lead_id: string;
  sent_at: string;
  opened_at: string | null;
}

export const outreachApi = {
  listDrafts: async (): Promise<DraftDTO[]> => (await api.get<DraftDTO[]>("/outreach/drafts")).data,

  approve: async (draftId: string): Promise<void> => {
    await api.post(`/outreach/drafts/${draftId}/approve`);
  },

  reject: async (draftId: string): Promise<void> => {
    await api.post(`/outreach/drafts/${draftId}/reject`);
  },

  send: async (draftId: string): Promise<void> => {
    await api.post(`/outreach/drafts/${draftId}/send`);
  },

  /** Sent-email history. Pass a leadId for the lead-scoped Emails tab. */
  listEmails: async (leadId?: string): Promise<SentEmailDTO[]> =>
    (await api.get<SentEmailDTO[]>("/outreach/emails", { params: leadId ? { lead_id: leadId } : undefined })).data,
};
