import { useApi } from "@/hooks/useApi";
import { leadsApi, type LeadDTO } from "@/lib/leadsApi";

/** Fetches the tenant's leads (assigned-only for a Sales Exec — enforced
 * server-side). Returns the four states every API-backed page needs. */
export function useLeads() {
  const { data, loading, error, refetch } = useApi<LeadDTO[]>(() => leadsApi.list(), [], {
    fallbackError: "Failed to load leads",
  });

  return { leads: data ?? [], loading, error, refetch };
}

/** A single lead — the Lead Details header and Overview tab. */
export function useLead(leadId: string) {
  const { data, loading, error, refetch } = useApi<LeadDTO>(() => leadsApi.get(leadId), [leadId], {
    fallbackError: "Failed to load lead",
  });

  return { lead: data, loading, error, refetch };
}
