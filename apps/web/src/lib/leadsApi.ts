import api from "@/lib/api";
import type { DealDTO } from "@/lib/dealsApi";
import type { LeadStatus } from "@/types";

export interface LeadDTO {
  id: string;
  name: string;
  industry: string | null;
  website: string | null;
  country: string | null;
  city: string | null;
  employees: number | null;
  annual_revenue: number | null;
  source: string | null;
  status: LeadStatus;
  priority: "high" | "medium" | "low" | null;
  owner_id: string | null;
  created_at: string;
}

export interface JobRef {
  job_id: string;
  status: string;
}

export interface ActivityDTO {
  id: string;
  lead_id: string;
  actor_id: string;
  activity_type: string;
  description: string;
  created_at: string;
}

export interface NoteDTO {
  id: string;
  lead_id: string;
  author_id: string;
  body: string;
  created_at: string;
}

export interface ContactDTO {
  id: string;
  lead_id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  job_title: string | null;
  department: string | null;
  is_primary: boolean;
}

export interface TimelineEventDTO {
  type: string;
  timestamp: string;
  summary: string | null;
}

export const leadsApi = {
  list: async (): Promise<LeadDTO[]> => (await api.get<LeadDTO[]>("/leads")).data,

  get: async (id: string): Promise<LeadDTO> => (await api.get<LeadDTO>(`/leads/${id}`)).data,

  create: async (data: {
    name: string;
    industry?: string;
    website?: string;
    country?: string;
    city?: string;
    employees?: number;
    source?: string;
  }): Promise<LeadDTO> => (await api.post<LeadDTO>("/leads", data)).data,

  assign: async (id: string, owner_id: string): Promise<LeadDTO> =>
    (await api.post<LeadDTO>(`/leads/${id}/assign`, { owner_id })).data,

  runIntelligence: async (id: string): Promise<JobRef> =>
    (await api.post<JobRef>(`/ai/leads/${id}/run-intelligence`)).data,

  activities: async (leadId: string): Promise<ActivityDTO[]> =>
    (await api.get<ActivityDTO[]>(`/leads/${leadId}/activities`)).data,

  createActivity: async ({
    leadId,
    activityType,
    description,
  }: {
    leadId: string;
    activityType: string;
    description: string;
  }): Promise<ActivityDTO> =>
    (await api.post<ActivityDTO>(`/leads/${leadId}/activities`, { activity_type: activityType, description })).data,

  notes: async (leadId: string): Promise<NoteDTO[]> => (await api.get<NoteDTO[]>(`/leads/${leadId}/notes`)).data,

  createNote: async ({ leadId, body }: { leadId: string; body: string }): Promise<NoteDTO> =>
    (await api.post<NoteDTO>(`/leads/${leadId}/notes`, { body })).data,

  deleteNote: async (noteId: string): Promise<void> => {
    await api.delete(`/leads/notes/${noteId}`);
  },

  contacts: async (leadId: string): Promise<ContactDTO[]> =>
    (await api.get<ContactDTO[]>(`/leads/${leadId}/contacts`)).data,

  deals: async (leadId: string): Promise<DealDTO[]> => (await api.get<DealDTO[]>(`/leads/${leadId}/deals`)).data,

  timeline: async (leadId: string): Promise<TimelineEventDTO[]> =>
    (await api.get<TimelineEventDTO[]>(`/leads/${leadId}/timeline`)).data,
};
