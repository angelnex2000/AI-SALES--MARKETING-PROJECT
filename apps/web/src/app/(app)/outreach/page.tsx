"use client";

import { useState } from "react";
import Link from "next/link";

import RequireRole from "@/components/auth/RequireRole";
import { AsyncBoundary, Panel } from "@/components/ui";
import { useOutreachDrafts } from "@/hooks/useOutreach";
import type { DraftStatus } from "@/lib/outreachApi";

const STATUS_META: Record<DraftStatus, { label: string; className: string }> = {
  pending_approval: { label: "Pending Gate 2 Review", className: "bg-amber-500/20 text-amber-300 border-amber-500/30" },
  approved: { label: "Approved (Ready to Send)", className: "bg-sky-500/20 text-sky-300 border-sky-500/30" },
  rejected: { label: "Rejected", className: "bg-rose-500/20 text-rose-300 border-rose-500/30" },
  sent: { label: "Sent to Recipient", className: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" },
};

export default function OutreachPage() {
  const { drafts, loading, error, actionError, pending, approve, reject, send } = useOutreachDrafts();
  const [activeChannel, setActiveChannel] = useState<"email" | "linkedin" | "whatsapp">("email");

  return (
    <div className="space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-indigo-400 font-mono">
            <span>OUTREACH CENTER</span> <span>/</span> <span>OMNICHANNEL GATE 2 HUB</span>
          </div>
          <h1 className="font-display text-3xl font-bold text-white tracking-tight mt-1">
            Omnichannel Outreach & Gate 2 Approval Hub
          </h1>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            Multi-channel outreach sequences (Email, LinkedIn, WhatsApp) with Gate 2 human safety approval and high-confidence auto-thresholding ($\ge 90\%$).
          </p>
        </div>

        {/* Omnichannel Channel Selector Tabs */}
        <div className="flex items-center gap-1 rounded-xl border border-slate-800 bg-slate-900/80 p-1">
          <button
            onClick={() => setActiveChannel("email")}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              activeChannel === "email"
                ? "bg-indigo-600 text-white shadow-md shadow-indigo-500/20"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            ✉️ Email
          </button>
          <button
            onClick={() => setActiveChannel("linkedin")}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              activeChannel === "linkedin"
                ? "bg-sky-600 text-white shadow-md shadow-sky-500/20"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            💼 LinkedIn InMail
          </button>
          <button
            onClick={() => setActiveChannel("whatsapp")}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
              activeChannel === "whatsapp"
                ? "bg-emerald-600 text-white shadow-md shadow-emerald-500/20"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            💬 WhatsApp Sequence
          </button>
        </div>
      </div>

      {/* Safety & RAG Grounding Guarantee Header */}
      <div className="glass-panel p-4 rounded-2xl flex flex-wrap items-center justify-between gap-4 border border-indigo-500/20 bg-indigo-500/5 text-xs">
        <div className="flex items-center gap-3 text-slate-300">
          <span className="text-xl">🛡️</span>
          <div>
            <span className="font-semibold text-white">Gate 2 Safety Protocol & Auto-Approval: </span>
            <span>Drafts with confidence $\ge 90\%$ and zero safety flags auto-approve for instant delivery.</span>
          </div>
        </div>

        <div className="flex items-center gap-3 font-mono">
          <span className="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-emerald-400 font-semibold">
            ✓ Smart Confidence Threshold (90%)
          </span>
          <span className="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-indigo-300 font-semibold">
            ✓ RAG Citation Verification
          </span>
        </div>
      </div>

      {actionError && (
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs font-semibold text-rose-300">
          ⚠️ {actionError}
        </div>
      )}

      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={drafts.length === 0}
        loadingMessage="Loading Gate 2 outreach drafts..."
        emptyMessage="No outreach drafts waiting — navigate to a lead to trigger AI Personalized Outreach generation."
      >
        <div className="space-y-5">
          {drafts.map((draft) => {
            const meta = STATUS_META[draft.status];
            return (
              <div
                key={draft.id}
                className="glass-panel glass-panel-hover rounded-2xl border border-slate-800 p-6 space-y-4"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
                  <div>
                    <div className="flex items-center gap-3">
                      <h2 className="font-display font-bold text-lg text-white">
                        {activeChannel === "email" ? draft.subject : activeChannel === "linkedin" ? `InMail: ${draft.subject}` : `WhatsApp: ${draft.subject}`}
                      </h2>
                      <span className={`px-2.5 py-1 rounded-full border text-xs font-semibold ${meta.className}`}>
                        {meta.label}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">
                      Recipient Lead:{" "}
                      <Link href={`/leads/${draft.lead_id}`} className="text-indigo-400 hover:underline font-semibold">
                        {draft.leadName}
                      </Link>
                    </p>
                  </div>
                </div>

                {/* Message Body Panel */}
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-xs font-sans text-slate-200 leading-relaxed whitespace-pre-line">
                  {draft.body}
                </div>

                {/* AI RAG Grounding & Explanation Footer */}
                {draft.explanation && (
                  <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-3.5 text-xs text-slate-300 flex items-start gap-2">
                    <span className="text-indigo-400 font-bold">🤖 RAG Reasoning:</span>
                    <span className="text-slate-400">{draft.explanation}</span>
                  </div>
                )}

                {/* Gate 2 Actions */}
                <div className="flex flex-wrap items-center justify-between gap-4 pt-2 border-t border-slate-800/80">
                  <div className="flex items-center gap-2 text-xs text-slate-400 font-mono">
                    <span>Channel: <strong className="text-white uppercase">{activeChannel}</strong></span>
                    <span>•</span>
                    <span>Model: <strong className="text-white">outreach-llm-v1</strong></span>
                  </div>

                  <RequireRole roles={["sales_executive", "sales_manager", "admin"]}>
                    <div className="flex items-center gap-3">
                      {draft.status === "pending_approval" && (
                        <>
                          <button
                            onClick={() => reject(draft.id)}
                            disabled={pending}
                            className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs font-semibold text-rose-300 hover:bg-rose-500/20 disabled:opacity-50 transition-all"
                          >
                            Reject
                          </button>
                          <button
                            onClick={() => approve(draft.id)}
                            disabled={pending}
                            className="rounded-xl bg-gradient-to-r from-sky-600 to-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-sky-500/20 hover:opacity-95 disabled:opacity-50 transition-all"
                          >
                            Approve Draft
                          </button>
                        </>
                      )}

                      {draft.status === "approved" && (
                        <button
                          onClick={() => send(draft.id)}
                          disabled={pending}
                          className="rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 px-5 py-2 text-xs font-semibold text-white shadow-lg shadow-emerald-500/20 hover:opacity-95 disabled:opacity-50 transition-all flex items-center gap-2"
                        >
                          <span>🚀</span> Deliver Message
                        </button>
                      )}
                    </div>
                  </RequireRole>
                </div>
              </div>
            );
          })}
        </div>
      </AsyncBoundary>
    </div>
  );
}
