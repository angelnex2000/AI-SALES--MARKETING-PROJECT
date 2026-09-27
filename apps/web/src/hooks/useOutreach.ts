import { useMemo } from "react";

import { useApi, useMutation } from "@/hooks/useApi";
import { leadsApi } from "@/lib/leadsApi";
import { outreachApi, type DraftDTO } from "@/lib/outreachApi";

export interface DraftWithLead extends DraftDTO {
  /** Resolved client-side — DraftResponse carries lead_id but no lead name. */
  leadName: string;
}

/**
 * Gate 2 state for the Outreach Center: the draft queue plus the three actions.
 *
 * Each action refetches instead of patching local state, so what's on screen is
 * what the server actually stored — important here, because approve/send are
 * `require_role(Role.SALES_EXECUTIVE)` and additionally scoped to the assigned
 * lead. A rejected action must not leave the UI showing an optimistic "Sent".
 */
export function useOutreachDrafts() {
  const { data, loading, error, refetch } = useApi(() => outreachApi.listDrafts(), [], {
    fallbackError: "Failed to load drafts",
  });
  const leads = useApi(() => leadsApi.list(), []);

  const drafts: DraftWithLead[] = useMemo(() => {
    const names = new Map((leads.data ?? []).map((l) => [l.id, l.name]));
    return (data ?? []).map((d) => ({ ...d, leadName: names.get(d.lead_id) ?? "Unknown lead" }));
  }, [data, leads.data]);

  const approve = useMutation(outreachApi.approve, "Could not approve the draft");
  const reject = useMutation(outreachApi.reject, "Could not reject the draft");
  const send = useMutation(outreachApi.send, "Could not send the email");

  const run = async (action: typeof approve, draftId: string) => {
    const result = await action.mutate(draftId);
    // mutate() resolves to null on failure — only refetch on success.
    if (result !== null) refetch();
  };

  return {
    drafts,
    loading: loading || leads.loading,
    error,
    actionError: approve.error ?? reject.error ?? send.error,
    pending: approve.pending || reject.pending || send.pending,
    approve: (draftId: string) => run(approve, draftId),
    reject: (draftId: string) => run(reject, draftId),
    send: (draftId: string) => run(send, draftId),
  };
}
