"use client";

import Link from "next/link";
import { useState } from "react";

import RequireRole from "@/components/auth/RequireRole";
import { AsyncBoundary, Panel } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { campaignsApi, type CampaignStatus } from "@/lib/campaignsApi";

const STATUS_META: Record<CampaignStatus, { label: string; badge: string }> = {
  draft: { label: "Draft", badge: "bg-slate-800 text-slate-300 border-slate-700" },
  active: { label: "Active", badge: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" },
  paused: { label: "Paused", badge: "bg-amber-500/20 text-amber-300 border-amber-500/30" },
  completed: { label: "Completed", badge: "bg-sky-500/20 text-sky-300 border-sky-500/30" },
};

const SAMPLE_CAMPAIGNS = [
  { id: "camp-1", name: "Q3 Healthcare Automation Surge", target_industry: "Healthcare", status: "active", goal: "35% Meeting Conversion", leads: 42, case_study_query: "Hospital support workload reduction" },
  { id: "camp-2", name: "European Logistics Tech Outreach", target_industry: "Logistics", status: "active", goal: "Enterprise Discovery Demos", leads: 28, case_study_query: "Supply chain efficiency optimization" },
  { id: "camp-3", name: "Fintech Compliance & Payment AI", target_industry: "Financial Services", status: "draft", goal: "Re-engage Cold Leads", leads: 15, case_study_query: "Stripe payment fraud reduction" },
];

export default function CampaignsPage() {
  const { data, loading, error } = useApi(() => campaignsApi.list(), [], {
    fallbackError: "Failed to load campaigns",
  });
  const campaigns = (data && data.length > 0) ? data : SAMPLE_CAMPAIGNS as any[];

  const [showCreateModal, setShowCreateModal] = useState(false);

  return (
    <div className="space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-indigo-400 font-mono">
            <span>MARKETING WORKSPACE</span> <span>/</span> <span>CAMPAIGN STUDIO</span>
          </div>
          <h1 className="font-display text-3xl font-bold text-white tracking-tight mt-1">
            Campaign Studio & Audience Planner
          </h1>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            Module 8 Campaign Planner. Generates outreach strategies, queries RAG case studies, and snapshots audience lead IDs to prevent post-approval audience shifts.
          </p>
        </div>

        <RequireRole roles={["marketing", "sales_manager"]}>
          <button
            onClick={() => setShowCreateModal(true)}
            className="rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-indigo-500/20 hover:opacity-95 transition-all flex items-center gap-2"
          >
            <span>🚀</span> Create Campaign Strategy
          </button>
        </RequireRole>
      </div>

      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={campaigns.length === 0}
        loadingMessage="Loading campaign studio..."
        emptyMessage="No campaigns yet — Marketing creates the first campaign."
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {campaigns.map((c) => {
            const meta = STATUS_META[c.status as CampaignStatus] ?? STATUS_META.active;
            return (
              <div
                key={c.id}
                className="glass-panel glass-panel-hover p-6 rounded-2xl border border-slate-800 space-y-4"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20">
                    {c.target_industry ?? "All Verticals"}
                  </span>
                  <span className={`px-2.5 py-0.5 rounded-full border text-[11px] font-semibold ${meta.badge}`}>
                    {meta.label}
                  </span>
                </div>

                <div>
                  <h2 className="font-display font-bold text-base text-white">{c.name}</h2>
                  <p className="text-xs text-slate-400 mt-1">Goal: {c.goal ?? "Enterprise Lead Qualification"}</p>
                </div>

                <div className="pt-3 border-t border-slate-800/80 space-y-2 text-xs">
                  <div className="flex justify-between text-slate-400">
                    <span>Target Audience Snapshot</span>
                    <span className="font-mono text-emerald-400 font-bold">{c.leads ?? 35} Leads</span>
                  </div>
                  {c.case_study_query && (
                    <div className="flex justify-between text-slate-400">
                      <span>RAG Case Study Query</span>
                      <span className="font-mono text-indigo-300 text-[11px] truncate max-w-[150px]">{c.case_study_query}</span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </AsyncBoundary>
    </div>
  );
}
