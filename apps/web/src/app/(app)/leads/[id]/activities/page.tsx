"use client";

import { AsyncBoundary, Panel } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { leadsApi } from "@/lib/leadsApi";
import { formatDateTime, humanize } from "@/lib/utils";

export default function LeadActivitiesPage({ params }: { params: { id: string } }) {
  // crm_activities — human-logged interactions only. AI actions show up on the
  // Timeline tab instead, so the two never get confused.
  const { data, loading, error } = useApi(() => leadsApi.activities(params.id), [params.id], {
    fallbackError: "Failed to load activities",
  });

  const activities = [...(data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));

  return (
    <Panel title="Activities">
      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={activities.length === 0}
        loadingMessage="Loading activities…"
        emptyMessage="No logged interactions yet."
      >
        <div className="divide-y divide-gray-100">
          {activities.map((a) => (
            <div key={a.id} className="flex items-start justify-between py-3 text-sm">
              <div>
                <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                  {humanize(a.activity_type)}
                </span>
                <span className="ml-2 text-gray-700">{a.description}</span>
              </div>
              <span className="whitespace-nowrap text-xs text-gray-400">{formatDateTime(a.created_at)}</span>
            </div>
          ))}
        </div>
      </AsyncBoundary>
    </Panel>
  );
}
