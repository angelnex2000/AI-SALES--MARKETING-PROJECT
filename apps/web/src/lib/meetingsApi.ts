import api from "@/lib/api";

/**
 * Meetings service (app/routers/meetings.py).
 *
 * Reading is Admin/Manager/Sales-Exec (Marketing gets nothing); booking and
 * slot suggestions are Sales Exec only. The list is assigned-only for a Sales
 * Exec, filtered server-side through the lead join.
 *
 * NOTE: the list endpoint takes no lead_id param, so the lead-scoped Meetings
 * tab filters client-side. Worth a backend param if the volume ever justifies it.
 */

export type MeetingStatus = "scheduled" | "completed" | "cancelled" | "no_show";

export interface MeetingDTO {
  id: string;
  lead_id: string;
  owner_id: string;
  scheduled_at: string;
  status: MeetingStatus;
  notes: string | null;
}

export const meetingsApi = {
  // No trailing slash — see the note in leadsApi.ts.
  list: async (): Promise<MeetingDTO[]> => (await api.get<MeetingDTO[]>("/meetings")).data,

  /** Meeting Scheduler agent — currently returns an empty list (agent stub). */
  suggestSlots: async (leadId: string, durationMinutes = 30): Promise<string[]> =>
    (
      await api.post<{ suggested_slots: string[] }>("/meetings/suggest-slots", {
        lead_id: leadId,
        duration_minutes: durationMinutes,
      })
    ).data.suggested_slots,
};
