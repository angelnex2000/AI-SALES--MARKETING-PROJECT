"use client";

import { AsyncBoundary, Panel } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { meetingsApi } from "@/lib/meetingsApi";
import { formatDateTime, humanize } from "@/lib/utils";

// READ-ONLY per CLAUDE.md — this tab shows this lead's meetings. Booking
// happens on the Meetings page.
export default function LeadMeetingsPage({ params }: { params: { id: string } }) {
  // GET /meetings takes no lead_id param, so filter here. The list is already
  // tenant- and assignment-scoped server-side, so this narrows, never widens.
  const { data, loading, error } = useApi(() => meetingsApi.list(), [], {
    fallbackError: "Failed to load meetings",
  });

  const meetings = (data ?? [])
    .filter((m) => m.lead_id === params.id)
    .sort((a, b) => b.scheduled_at.localeCompare(a.scheduled_at));

  return (
    <Panel title="Meetings">
      <p className="mb-3 text-xs text-gray-400">Read-only. Book and reschedule from the Meetings page.</p>
      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={meetings.length === 0}
        loadingMessage="Loading meetings…"
        emptyMessage="No meetings booked with this lead."
      >
        <div className="divide-y divide-gray-100">
          {meetings.map((m) => (
            <div key={m.id} className="flex items-center justify-between py-3 text-sm">
              <span className="text-gray-800">{m.notes ?? "Meeting"}</span>
              <span className="flex items-center gap-3">
                <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{humanize(m.status)}</span>
                <span className="whitespace-nowrap text-xs text-gray-400">{formatDateTime(m.scheduled_at)}</span>
              </span>
            </div>
          ))}
        </div>
      </AsyncBoundary>
    </Panel>
  );
}
