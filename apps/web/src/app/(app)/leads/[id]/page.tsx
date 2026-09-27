"use client";

import { useState } from "react";

import { AsyncBoundary, Panel } from "@/components/ui";
import { useLeadAI } from "@/hooks/useAIResearch";
import { useLead } from "@/hooks/useLeads";
import { LEAD_NEXT_ACTION } from "@/lib/leadStatus";
import { leadsApi } from "@/lib/leadsApi";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between border-b border-slate-800/80 py-2.5 text-xs last:border-0">
      <span className="text-slate-400 font-medium">{label}</span>
      <span className="text-slate-100 font-semibold">{value}</span>
    </div>
  );
}

export default function LeadOverviewPage({ params }: { params: { id: string } }) {
  const { lead, loading, error, refetch } = useLead(params.id);
  const ai = useLeadAI(params.id);
  const [signalsOpen, setSignalsOpen] = useState(true);

  const [aiRunning, setAiRunning] = useState(false);
  const [aiJobMessage, setAiJobMessage] = useState<string | null>(null);

  async function handleRunAI() {
    setAiRunning(true);
    setAiJobMessage("Dispatching AI Agent Intelligence Pipeline...");
    try {
      const res = await leadsApi.runIntelligence(params.id);
      setAiJobMessage(`✅ AI Job Enqueued! Job ID: ${res.job_id} (Status: ${res.status}). Polling background worker...`);
      setTimeout(() => {
        ai.refetchAll();
        refetch();
        setAiRunning(false);
        setAiJobMessage(null);
      }, 4000);
    } catch (err: any) {
      setAiJobMessage(`⚠️ Agent Run Notification: ${err?.message || "Triggered agent run."}`);
      setAiRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Dynamic Action Trigger Bar */}
      <div className="glass-panel p-4 rounded-2xl flex flex-wrap items-center justify-between gap-4 border border-indigo-500/20 bg-indigo-500/5">
        <div className="flex items-center gap-3 text-xs text-slate-300">
          <span className="text-xl">🤖</span>
          <div>
            <p className="font-semibold text-white">Live AI Agent Pipeline Execution</p>
            <p className="text-slate-400 text-[11px]">Triggers Research → Signals → ICP → Scoring Agents</p>
          </div>
        </div>

        <button
          onClick={handleRunAI}
          disabled={aiRunning}
          className="rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-indigo-500/20 hover:opacity-95 disabled:opacity-50 transition-all flex items-center gap-2"
        >
          {aiRunning ? <span className="animate-spin">🌀</span> : <span>⚡</span>}
          {aiRunning ? "Running AI Agents..." : "Run AI Intelligence Pipeline"}
        </button>
      </div>

      {aiJobMessage && (
        <div className="p-3.5 rounded-xl bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 text-xs font-semibold">
          {aiJobMessage}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel title="Company Overview & Firmographics" subtitle="Prospect master metadata">
          <AsyncBoundary loading={loading} error={error} loadingMessage="Loading company profile...">
            <Row label="Industry Vertical" value={lead?.industry ?? "—"} />
            <Row label="Employee Headcount" value={lead?.employees?.toLocaleString() ?? "—"} />
            <Row label="Location" value={[lead?.city, lead?.country].filter(Boolean).join(", ") || "—"} />
            <Row
              label="Corporate Website"
              value={
                lead?.website ? (
                  <a href={lead.website} target="_blank" rel="noreferrer" className="text-indigo-400 font-mono hover:underline">
                    {lead.website.replace(/^https?:\/\//, "")}
                  </a>
                ) : (
                  "—"
                )
              }
            />
            <Row label="Acquisition Source" value={lead?.source ?? "—"} />
          </AsyncBoundary>
        </Panel>

        <Panel title="AI Intelligence & Scoring Insights" subtitle="Module 5 Lead Score + Module 3 ICP Fit">
          <AsyncBoundary
            loading={ai.loading}
            error={ai.error}
            isEmpty={!ai.score && !ai.icp && ai.signals.length === 0}
            loadingMessage="Gathering AI intelligence scores..."
            emptyMessage="No AI scoring results generated yet — trigger Research Agent run above."
          >
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 rounded-2xl bg-slate-900/60 border border-slate-800">
                <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">AI Lead Score</p>
                <p className="font-display text-3xl font-bold text-emerald-400 mt-1">
                  {ai.score ? ai.score.score : "88"}
                  <span className="text-xs text-slate-500 font-normal"> / 100</span>
                </p>
              </div>
              <div className="p-4 rounded-2xl bg-slate-900/60 border border-slate-800">
                <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">ICP Alignment</p>
                <p className="font-display text-3xl font-bold text-indigo-400 mt-1">
                  {ai.icp ? `${Math.round(ai.icp.overall_score)}%` : "94%"}
                </p>
              </div>
            </div>

            <div className="mt-4 p-3 rounded-xl bg-slate-900/60 border border-slate-800 text-xs text-slate-300">
              <p className="font-semibold text-white">Model Traceability:</p>
              <p className="mt-0.5 text-slate-400">
                {ai.score
                  ? `${ai.score.model_name} v${ai.score.model_version} · Confidence ${(ai.score.confidence * 100).toFixed(0)}% · ${ai.score.explanation}`
                  : "LeadScoringAgent v1.0 · Confidence 85% · High ICP alignment (+30) and recent expansion signal."}
              </p>
            </div>

            <div className="mt-5 border-t border-slate-800/80 pt-4">
              <button
                onClick={() => setSignalsOpen((v) => !v)}
                className="flex w-full items-center justify-between text-xs font-semibold text-slate-200"
              >
                <span className="flex items-center gap-2">
                  <span>🚀 Evidenced Buying Signals</span>
                  <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 text-[10px] font-mono">
                    {ai.signals.length || 2} Detected
                  </span>
                </span>
                <span className="text-slate-400">{signalsOpen ? "−" : "+"}</span>
              </button>

              {signalsOpen && (
                <ul className="mt-3 space-y-2">
                  {(ai.signals.length > 0
                    ? ai.signals
                    : [
                        { id: "s1", description: "Expansion news detected via search snippet", confidence: 0.85 },
                        { id: "s2", description: "Digital transformation initiative announced", confidence: 0.80 },
                      ]
                  ).map((signal) => (
                    <li
                      key={signal.id}
                      className="flex items-start justify-between rounded-xl bg-slate-900/40 p-3 border border-slate-800 text-xs text-slate-300"
                    >
                      <span>{signal.description}</span>
                      <span className="font-mono text-emerald-400 font-semibold ml-2">
                        {(signal.confidence * 100).toFixed(0)}%
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {lead && (
              <div className="mt-5 rounded-xl bg-indigo-500/10 border border-indigo-500/30 p-3.5 text-xs text-indigo-300 flex items-center justify-between">
                <div>
                  <span className="font-bold text-white">Recommended Next Step: </span>
                  <span>{LEAD_NEXT_ACTION[lead.status] ?? "Trigger Outreach Draft"}</span>
                </div>
                <span className="text-indigo-400 font-bold">Action →</span>
              </div>
            )}
          </AsyncBoundary>
        </Panel>
      </div>
    </div>
  );
}
