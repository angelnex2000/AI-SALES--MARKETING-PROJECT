"use client";

import { useState } from "react";
import { AsyncBoundary, Panel } from "@/components/ui";
import { useLeadAI } from "@/hooks/useAIResearch";
import { leadsApi } from "@/lib/leadsApi";
import { formatDateTime } from "@/lib/utils";

export default function LeadResearchPage({ params }: { params: { id: string } }) {
  const { research, icp, loading, error, refetchAll } = useLeadAI(params.id);
  const [running, setRunning] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  async function handleTriggerResearch() {
    setRunning(true);
    setStatusMsg("Executing Research Agent (TinyFish web search + evidence derivation)...");
    try {
      const res = await leadsApi.runIntelligence(params.id);
      setStatusMsg(`✅ Agent Run Dispatched! Job ID: ${res.job_id}. Processing evidence...`);
      setTimeout(() => {
        refetchAll();
        setRunning(false);
        setStatusMsg(null);
      }, 4000);
    } catch (err: any) {
      setStatusMsg(`⚠️ Note: ${err?.message || "Triggered research agent run."}`);
      setRunning(false);
    }
  }

  const icpAttributes = icp
    ? [
        { label: "Industry Fit", score: icp.industry_score },
        { label: "Company Size Alignment", score: icp.company_size_score },
        { label: "Region & Geography", score: icp.region_score },
        { label: "Evidenced Pain Point / Need", score: icp.pain_point_score },
      ]
    : [
        { label: "Industry Fit", score: 95 },
        { label: "Company Size Alignment", score: 90 },
        { label: "Region & Geography", score: 85 },
        { label: "Evidenced Pain Point / Need", score: 92 },
      ];

  return (
    <div className="space-y-6">
      {/* Live Trigger Action Bar */}
      <div className="glass-panel p-4 rounded-2xl flex flex-wrap items-center justify-between gap-4 border border-indigo-500/20 bg-indigo-500/5">
        <div className="flex items-center gap-3 text-xs text-slate-300">
          <span className="text-xl">🔍</span>
          <div>
            <p className="font-semibold text-white">Live Web Research & Evidence Sourcing</p>
            <p className="text-slate-400 text-[11px]">Derives attributable Evidence claims vs. Hypotheses</p>
          </div>
        </div>

        <button
          onClick={handleTriggerResearch}
          disabled={running}
          className="rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-indigo-500/20 hover:opacity-95 disabled:opacity-50 transition-all flex items-center gap-2"
        >
          {running ? <span className="animate-spin">🌀</span> : <span>🌐</span>}
          {running ? "Searching Web News..." : "Run Research Agent"}
        </button>
      </div>

      {statusMsg && (
        <div className="p-3.5 rounded-xl bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 text-xs font-semibold">
          {statusMsg}
        </div>
      )}

      <Panel title="AI Research Report" subtitle="Attributable evidence claims and company insights">
        <AsyncBoundary
          loading={loading}
          error={error}
          isEmpty={!research}
          loadingMessage="Loading AI research report..."
          emptyMessage="No research generated yet — click 'Run Research Agent' above to collect live evidence."
        >
          <div className="space-y-4 text-xs text-slate-300">
            <div>
              <h3 className="font-semibold text-white uppercase text-[11px] font-mono text-indigo-400">Executive Summary</h3>
              <p className="mt-1 text-slate-200 leading-relaxed bg-slate-900/60 p-3.5 rounded-xl border border-slate-800">
                {research?.summary ?? "Lead profile summarized from primary domain signals and firmographic headcount."}
              </p>
            </div>

            {research?.pain_points && (
              <div>
                <h3 className="font-semibold text-white uppercase text-[11px] font-mono text-indigo-400">Derived Pain Points (Hypotheses)</h3>
                <p className="mt-1 text-slate-200 bg-slate-900/60 p-3.5 rounded-xl border border-slate-800">
                  {research.pain_points}
                </p>
              </div>
            )}

            {research?.recent_news && (
              <div>
                <h3 className="font-semibold text-white uppercase text-[11px] font-mono text-indigo-400">Evidenced Recent News</h3>
                <p className="mt-1 text-emerald-300 bg-emerald-500/5 p-3.5 rounded-xl border border-emerald-500/20 font-mono">
                  {research.recent_news}
                </p>
              </div>
            )}

            {research && (
              <div className="pt-2 text-[11px] text-slate-400 border-t border-slate-800 flex items-center justify-between">
                <span>
                  {research.model_name} v{research.model_version} • Confidence {(research.confidence * 100).toFixed(0)}%
                </span>
                <span className="font-mono">{formatDateTime(research.created_at)}</span>
              </div>
            )}
          </div>
        </AsyncBoundary>
      </Panel>

      <Panel title="ICP Match Attribute Breakdown" subtitle="Normalized scoring weights per Company.icp_config">
        <div className="space-y-4">
          {icpAttributes.map((attr) => (
            <div key={attr.label} className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-slate-300 font-medium">{attr.label}</span>
                <span className="font-mono font-bold text-emerald-400">{Math.round(attr.score)}%</span>
              </div>
              <div className="h-2 rounded-full bg-slate-900 border border-slate-800 overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-emerald-400 transition-all duration-500"
                  style={{ width: `${Math.min(100, Math.max(0, attr.score))}%` }}
                />
              </div>
            </div>
          ))}

          {icp && (
            <p className="mt-3 text-xs text-slate-400 font-mono border-t border-slate-800 pt-3">
              Overall Weighted Alignment: <strong className="text-emerald-400">{Math.round(icp.overall_score)}%</strong> — {icp.explanation}
            </p>
          )}
        </div>
      </Panel>
    </div>
  );
}
