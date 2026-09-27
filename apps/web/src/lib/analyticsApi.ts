import api from "@/lib/api";

/**
 * Analytics service (app/routers/analytics.py). Every aggregate is already
 * company_id-filtered server-side, and a Sales Exec's numbers cover only their
 * assigned leads.
 *
 * RBAC: `dashboard` and `leadsByStatus` are open to any signed-in user;
 * `revenue` and `teamPerformance` are Admin/Manager only — call them behind a
 * useRole check rather than letting a Sales Exec collect 403s.
 */

export interface DashboardStats {
  total_leads: number;
  open_deals: number;
  meetings: number;
}

export interface RevenueStats {
  closed_won_revenue: number;
  open_pipeline: number;
}

export interface TeamPerformanceRow {
  owner_id: string | null;
  leads: number;
}

export const analyticsApi = {
  dashboard: async (): Promise<DashboardStats> => (await api.get<DashboardStats>("/analytics/dashboard")).data,

  revenue: async (): Promise<RevenueStats> => (await api.get<RevenueStats>("/analytics/revenue")).data,

  teamPerformance: async (): Promise<TeamPerformanceRow[]> =>
    (await api.get<TeamPerformanceRow[]>("/analytics/team-performance")).data,

  /** Lead counts keyed by status enum value. */
  leadsByStatus: async (): Promise<Record<string, number>> =>
    (await api.get<Record<string, number>>("/analytics/leads")).data,
};
