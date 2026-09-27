"use client";

import { AsyncBoundary, Panel } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { leadsApi } from "@/lib/leadsApi";
import { formatDateTime, humanize } from "@/lib/utils";

export default function LeadTimelinePage({ params }: { params: { id: string } }) {
  // Computed server-side, not a table — merges human activities, AI research,
  // and sent emails into one chronological feed.
  const { data, loading, error } = useApi(() => leadsApi.timeline(params.id), [params.id], {
    fallbackError: "Failed to load the timeline",
  });

  // The API returns oldest-first; newest-first reads better as a story so far.
  const events = [...(data ?? [])].reverse();

  return (
    <Panel title="Timeline">
      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={events.length === 0}
        loadingMessage="Loading the timeline…"
        emptyMessage="Nothing has happened with this lead yet."
      >
        <ol className="relative ml-2 border-l border-gray-200">
          {events.map((e, i) => (
            <li key={`${e.type}-${e.timestamp}-${i}`} className="mb-4 ml-4 last:mb-0">
              <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border-2 border-white bg-indigo-500" />
              <p className="text-sm text-gray-800">{e.summary ?? humanize(e.type)}</p>
              <p className="text-xs text-gray-400">
                {humanize(e.type)} · {formatDateTime(e.timestamp)}
              </p>
            </li>
          ))}
        </ol>
      </AsyncBoundary>
    </Panel>
  );
}
