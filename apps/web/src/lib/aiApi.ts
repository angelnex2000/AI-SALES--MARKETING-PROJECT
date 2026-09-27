import api from "@/lib/api";

/**
 * AI results service (app/routers/ai.py).
 *
 * IMPORTANT: every getter returns an ARRAY, newest first. AI outputs are
 * append-only history tables (AIOutputMixin), never mutable fields on the lead —
 * that's what makes "why did the score change last Tuesday" answerable. Take
 * [0] for the current value, and treat [] as "the agents haven't run yet",
 * which is the normal state for a fresh lead, not an error.
 *
 * Every row carries model_name + model_version + confidence + explanation, so
 * the UI can always show what produced a number rather than the bare number.
 */

interface AIOutput {
  id: string;
  model_name: string;
  model_version: string;
  confidence: number;
  explanation: string;
}

export interface ResearchReportDTO extends AIOutput {
  lead_id: string;
  summary: string;
  industry_insights: string | null;
  company_size_estimate: string | null;
  recent_news: string | null;
  pain_points: string | null;
  sources: string | null;
  created_at: string;
}

export interface LeadScoreDTO extends AIOutput {
  lead_id: string;
  score: number;
  created_at: string;
}

export interface BuyingSignalDTO extends AIOutput {
  lead_id: string;
  signal_type: string;
  description: string;
  source_url: string | null;
  detected_at: string;
}

export interface ICPScoreDTO extends AIOutput {
  lead_id: string;
  industry_score: number;
  company_size_score: number;
  region_score: number;
  pain_point_score: number;
  overall_score: number;
}

export interface RevenueForecastDTO {
  id: string;
  forecast_period: string;
  predicted_revenue: number;
  confidence: number;
  model_name: string;
  model_version: string;
  input_summary: string | null;
  created_at: string;
}

export interface JobDTO {
  id: string;
  job_type: string;
  lead_id: string | null;
  status: "pending" | "running" | "completed" | "failed";
  result: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export const aiApi = {
  research: async (leadId: string): Promise<ResearchReportDTO[]> =>
    (await api.get<ResearchReportDTO[]>(`/ai/leads/${leadId}/research`)).data,

  score: async (leadId: string): Promise<LeadScoreDTO[]> =>
    (await api.get<LeadScoreDTO[]>(`/ai/leads/${leadId}/score`)).data,

  buyingSignals: async (leadId: string): Promise<BuyingSignalDTO[]> =>
    (await api.get<BuyingSignalDTO[]>(`/ai/leads/${leadId}/buying-signals`)).data,

  icpScore: async (leadId: string): Promise<ICPScoreDTO[]> =>
    (await api.get<ICPScoreDTO[]>(`/ai/leads/${leadId}/icp-score`)).data,

  /** Admin/Manager only — deal-based revenue forecasting. */
  forecast: async (): Promise<RevenueForecastDTO[]> =>
    (await api.get<RevenueForecastDTO[]>("/ai/forecast")).data,

  /** 202 + job_id: the agents are slow, so poll getJob() rather than blocking. */
  runForecast: async (): Promise<{ job_id: string; status: string }> =>
    (await api.post<{ job_id: string; status: string }>("/ai/forecast/run")).data,

  getJob: async (jobId: string): Promise<JobDTO> => (await api.get<JobDTO>(`/jobs/${jobId}`)).data,
};
