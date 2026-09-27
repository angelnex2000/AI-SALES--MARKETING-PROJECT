"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import LeadScoreBadge from "@/components/leads/LeadScoreBadge";
import { useApi } from "@/hooks/useApi";
import { useRunIntelligence } from "@/hooks/useAIResearch";
import { useLead } from "@/hooks/useLeads";
import { aiApi } from "@/lib/aiApi";
import { LEAD_STATUS_META } from "@/lib/leadStatus";

// Lead Details is ONE page with tabs (CLAUDE.md) — these are nested routes
// rendered inside this shared shell, never separate top-level pages. Buying
// Signals is deliberately NOT a tab; it lives inline in the Overview AI
// Insights card.
const TABS = [
  { seg: "", label: "Overview" },
  { seg: "research", label: "AI Research" },
  { seg: "activities", label: "Activities" },
  { seg: "timeline", label: "Timeline" },
  { seg: "emails", label: "Emails" },
  { seg: "meetings", label: "Meetings" },
  { seg: "notes", label: "Notes" },
];

export default function LeadDetailLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { id: string };
}) {
  const pathname = usePathname();
  const base = `/leads/${params.id}`;

  // Tenant + assigned-only are enforced server-side; a Sales Exec hitting an
  // unassigned id gets a 404 (never a 403 — that would confirm it exists).
  const { lead, loading, error } = useLead(params.id);
  const score = useApi(() => aiApi.score(params.id), [params.id]);
  const intelligence = useRunIntelligence(params.id, () => score.refetch());

  const status = lead ? LEAD_STATUS_META[lead.status] : null;

  if (loading) {
    return <div className="text-sm text-gray-400">Loading lead…</div>;
  }

  if (error || !lead) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-10 text-center text-sm text-red-700">
        {error ?? "Not found."}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold text-gray-900">{lead.name}</h1>
            {/* null until the scoring model has run for this lead. */}
            <LeadScoreBadge score={score.data?.[0]?.score ?? null} />
            {status && (
              <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${status.className}`}>
                {status.label}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-gray-500">{lead.industry ?? "Industry unknown"}</p>
        </div>

        {/* Quick actions. Sending/booking live on their own pages (Gate 2 lives
            only in Outreach Center), so those two are links, not in-place actions. */}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={intelligence.start}
            disabled={intelligence.running}
            className="rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
          >
            {intelligence.running ? "Running AI…" : "Generate Research"}
          </button>
          <Link
            href="/outreach"
            className="rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800"
          >
            Generate Outreach
          </Link>
          <Link
            href="/meetings"
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Schedule Meeting
          </Link>
          <button className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            Change Status
          </button>
        </div>
      </div>

      {intelligence.error && <p className="text-sm text-red-600">{intelligence.error}</p>}
      {intelligence.running && (
        <p className="text-xs text-gray-400">
          The research, buying-signal, ICP, and scoring agents run in the background — this refreshes when they finish.
        </p>
      )}

      <nav className="flex flex-wrap gap-1 border-b border-gray-200">
        {TABS.map((tab) => {
          const href = tab.seg ? `${base}/${tab.seg}` : base;
          const active = pathname === href;
          return (
            <Link
              key={tab.label}
              href={href}
              className={`-mb-px border-b-2 px-3 py-2 text-sm ${
                active
                  ? "border-gray-900 font-semibold text-gray-900"
                  : "border-transparent text-gray-500 hover:text-gray-800"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>

      <div>{children}</div>
    </div>
  );
}
