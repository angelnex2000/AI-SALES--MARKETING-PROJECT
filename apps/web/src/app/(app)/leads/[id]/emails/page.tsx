"use client";

import { AsyncBoundary, Panel } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { outreachApi } from "@/lib/outreachApi";
import { formatDateTime } from "@/lib/utils";

// READ-ONLY per CLAUDE.md — this tab shows email history/status for the lead.
// Actual sending + Gate 2 approval happen only in the Outreach Center.
export default function LeadEmailsPage({ params }: { params: { id: string } }) {
  const { data, loading, error } = useApi(() => outreachApi.listEmails(params.id), [params.id], {
    fallbackError: "Failed to load emails",
  });

  const emails = [...(data ?? [])].sort((a, b) => b.sent_at.localeCompare(a.sent_at));

  return (
    <Panel title="Emails">
      <p className="mb-3 text-xs text-gray-400">Read-only history. Draft, approve, and send from the Outreach Center.</p>
      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={emails.length === 0}
        loadingMessage="Loading emails…"
        emptyMessage="No emails sent to this lead yet."
      >
        <div className="divide-y divide-gray-100">
          {emails.map((e) => (
            <div key={e.id} className="flex items-center justify-between py-3 text-sm">
              {/* The list endpoint returns delivery status only — subject lives
                  on the draft that produced it. */}
              <span className="text-gray-800">Outreach email</span>
              <span className="flex items-center gap-3">
                <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                  {e.opened_at ? "Opened" : "Sent"}
                </span>
                <span className="whitespace-nowrap text-xs text-gray-400">{formatDateTime(e.sent_at)}</span>
              </span>
            </div>
          ))}
        </div>
      </AsyncBoundary>
    </Panel>
  );
}
