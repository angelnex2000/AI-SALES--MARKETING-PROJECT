import api from "@/lib/api";

/**
 * Billing service (app/routers/billing.py) — Admin only, every endpoint.
 * Reads are views over provider state; the authoritative updates arrive via the
 * signed webhook, not from these calls.
 */

export interface SubscriptionDTO {
  id: string;
  plan_name: string;
  status: string;
  user_limit: number;
  ai_credit_limit: number;
}

export interface UsageDTO {
  records: number;
}

export const billingApi = {
  /** null when the tenant has no subscription row yet — not an error. */
  subscription: async (): Promise<SubscriptionDTO | null> =>
    (await api.get<SubscriptionDTO | null>("/billing/subscription")).data,

  usage: async (): Promise<UsageDTO> => (await api.get<UsageDTO>("/billing/usage")).data,

  /** Provider-sourced; returns [] until the billing provider is wired. */
  invoices: async (): Promise<unknown[]> => (await api.get<unknown[]>("/billing/invoices")).data,
};
