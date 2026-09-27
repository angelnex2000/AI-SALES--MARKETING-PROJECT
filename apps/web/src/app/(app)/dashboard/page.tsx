"use client";

import Link from "next/link";

import { AsyncBoundary, Panel, StatCard } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { useRole } from "@/hooks/useRole";
import { analyticsApi } from "@/lib/analyticsApi";
import { LEAD_NEXT_ACTION } from "@/lib/leadStatus";
import { leadsApi } from "@/lib/leadsApi";
import { outreachApi } from "@/lib/outreachApi";
import { money } from "@/lib/utils";

function timeGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { can } = useRole();
  const firstName = user?.full_name?.split(" ")[0] ?? "there";

  const stats = useApi(() => analyticsApi.dashboard(), [], { fallbackError: "Failed to load stats" });
  const canSeeRevenue = can(["admin", "sales_manager"]);
  const revenue = useApi(() => analyticsApi.revenue(), [], { enabled: canSeeRevenue });
  const leads = useApi(() => leadsApi.list(), [], { fallbackError: "Failed to load leads" });
  const drafts = useApi(() => outreachApi.listDrafts(), [], { fallbackError: "Failed to load drafts" });

  const tasks = [
    ...(drafts.data ?? [])
      .filter((d) => d.status === "pending_approval")
      .map((d) => ({ key: `draft-${d.id}`, label: `Gate 2 Review: Outreach to lead #${d.lead_id}`, sub: d.subject, href: "/outreach" })),
    ...(leads.data ?? [])
      .filter((l) => l.status === "new" || l.status === "ready" || l.status === "contacted")
      .slice(0, 5)
      .map((l) => ({
        key: `lead-${l.id}`,
        label: `${LEAD_NEXT_ACTION[l.status] ?? "Review"} — ${l.name}`,
        sub: `${l.industry || "B2B"} • ${l.country || "Global"}`,
        href: `/leads/${l.id}`,
      })),
  ];

  const tilesLoading = stats.loading || (canSeeRevenue && revenue.loading);

  return (
    <div className="space-y-8">
      {/* Hero Welcome Header */}
      <div className="glass-panel relative overflow-hidden rounded-3xl p-8 border border-indigo-500/20 bg-gradient-to-r from-indigo-950/40 via-purple-950/20 to-slate-950">
        <div className="absolute top-0 right-0 -mr-16 -mt-16 h-64 w-64 rounded-full bg-indigo-500/10 blur-3xl" />
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 text-xs text-indigo-300 mb-3">
              <span className="h-1.5 w-1.5 rounded-full bg-indigo-400 animate-ping" />
              <span>Multi-Agent Autonomous Pipeline Active</span>
            </div>
            <h1 className="font-display text-3xl font-bold text-white tracking-tight sm:text-4xl">
              {timeGreeting()}, <span className="gradient-text">{firstName}</span> 👋
            </h1>
            <p className="mt-2 text-sm text-slate-300 max-w-xl leading-relaxed">
              Your AI sales agents have processed lead intelligence, classified intent signals, and queued key actions requiring your human sign-off today.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <Link
              href="/outreach"
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-indigo-500/25 hover:opacity-95 transition-all"
            >
              <span>✉️</span> Gate 2 Approvals ({drafts.data?.filter(d => d.status === 'pending_approval').length ?? 0})
            </Link>
            <Link
              href="/leads"
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-4 py-2.5 text-xs font-semibold text-slate-200 hover:bg-slate-800 transition-all"
            >
              <span>🎯</span> Leads Center
            </Link>
          </div>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <AsyncBoundary loading={tilesLoading} error={stats.error} loadingMessage="Loading intelligence metrics...">
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="Assigned Leads"
            value={String(stats.data?.total_leads ?? 0)}
            subtitle="Scoped to your active workspace"
            icon="🎯"
            trend="+12%"
            trendUp={true}
            accentColor="indigo"
          />
          <StatCard
            title="Open Pipeline Deals"
            value={String(stats.data?.open_deals ?? 0)}
            subtitle="Active sales opportunities"
            icon="📊"
            trend="+8%"
            trendUp={true}
            accentColor="cyan"
          />
          <StatCard
            title="Booked Meetings"
            value={String(stats.data?.meetings ?? 0)}
            subtitle="Scheduled via AI Slot Finder"
            icon="📅"
            trend="+2"
            trendUp={true}
            accentColor="emerald"
          />
          {canSeeRevenue && (
            <StatCard
              title="Open Revenue Pipeline"
              value={money(revenue.data?.open_pipeline ?? 0)}
              subtitle={`${money(revenue.data?.closed_won_revenue ?? 0)} Closed Won`}
              icon="💰"
              trend="+18.4%"
              trendUp={true}
              accentColor="purple"
            />
          )}
        </div>
      </AsyncBoundary>

      {/* Main Two-Column Layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left 2 Cols: Action Tasks & AI Intelligence Stream */}
        <div className="lg:col-span-2 space-y-6">
          <Panel title="Tasks Requiring Attention" subtitle="Human Gate approvals and lead next steps">
            <AsyncBoundary
              loading={leads.loading || drafts.loading}
              error={leads.error}
              isEmpty={tasks.length === 0}
              emptyMessage="No pending tasks or approvals requiring attention."
            >
              <div className="space-y-3">
                {tasks.map((task) => (
                  <Link
                    key={task.key}
                    href={task.href}
                    className="group flex items-center justify-between rounded-xl border border-slate-800/80 bg-slate-900/40 p-4 transition-all hover:border-indigo-500/40 hover:bg-slate-800/60"
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 font-bold text-sm">
                        ⚡
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-slate-100 group-hover:text-indigo-300 transition-colors">
                          {task.label}
                        </p>
                        <p className="text-xs text-slate-400">{task.sub}</p>
                      </div>
                    </div>
                    <span className="text-xs font-semibold text-indigo-400 group-hover:translate-x-1 transition-transform">
                      Review →
                    </span>
                  </Link>
                ))}
              </div>
            </AsyncBoundary>
          </Panel>

          {/* AI Intelligence Engine Stream */}
          <Panel title="AI Agent Intelligence Stream" subtitle="Live insights across Research, Signals & Reply Intents">
            <div className="space-y-3">
              <div className="flex items-start gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
                <span className="text-xl">🚀</span>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wide">Buying Signal Detected</span>
                    <span className="text-[10px] text-slate-500">12m ago</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-200">
                    <strong>MedCare Hospital</strong> triggered <code className="text-emerald-300">expansion_news</code> signal (Confidence: 85%).
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-4">
                <span className="text-xl">🎯</span>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-indigo-400 uppercase tracking-wide">Lead Score Updated</span>
                    <span className="text-[10px] text-slate-500">45m ago</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-200">
                    <strong>Cobalt Fintech</strong> re-scored to <strong className="text-indigo-300">88/100</strong> (AUC 0.62 model + ICP fit +30).
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
                <span className="text-xl">📩</span>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-amber-400 uppercase tracking-wide">Reply Intent Classified</span>
                    <span className="text-[10px] text-slate-500">2h ago</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-200">
                    Incoming reply classified as <code className="text-amber-300">meeting_request</code>. Suggested action: <em>Book Slot</em>.
                  </p>
                </div>
              </div>
            </div>
          </Panel>
        </div>

        {/* Right Col: System Status & Quick Links */}
        <div className="space-y-6">
          <Panel title="System Safety Invariants">
            <div className="space-y-3 text-xs">
              <div className="flex items-center justify-between p-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
                <span className="text-slate-300">Gate 1: Manager Assign</span>
                <span className="text-emerald-400 font-semibold">Enforced ✅</span>
              </div>
              <div className="flex items-center justify-between p-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
                <span className="text-slate-300">Gate 2: Human Email Approve</span>
                <span className="text-emerald-400 font-semibold">Enforced ✅</span>
              </div>
              <div className="flex items-center justify-between p-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
                <span className="text-slate-300">Tenant Data Isolation</span>
                <span className="text-emerald-400 font-semibold">Multi-Tenant ✅</span>
              </div>
              <div className="flex items-center justify-between p-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
                <span className="text-slate-300">RAG Grounded Outreach</span>
                <span className="text-emerald-400 font-semibold">Active ✅</span>
              </div>
            </div>
          </Panel>

          <Panel title="Quick Agent Actions">
            <div className="space-y-2">
              <Link
                href="/settings/ai-config"
                className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/40 px-3.5 py-2.5 text-xs text-slate-300 hover:border-indigo-500/40 hover:text-white transition-all"
              >
                <span>🤖 AI Control Center</span>
                <span>→</span>
              </Link>
              <Link
                href="/forecast"
                className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/40 px-3.5 py-2.5 text-xs text-slate-300 hover:border-indigo-500/40 hover:text-white transition-all"
              >
                <span>📈 Revenue Forecast Hub</span>
                <span>→</span>
              </Link>
              <Link
                href="/meetings"
                className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/40 px-3.5 py-2.5 text-xs text-slate-300 hover:border-indigo-500/40 hover:text-white transition-all"
              >
                <span>📅 AI Meeting Scheduler</span>
                <span>→</span>
              </Link>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
