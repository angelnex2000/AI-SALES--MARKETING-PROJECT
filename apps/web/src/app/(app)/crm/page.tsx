"use client";

import { useState } from "react";
import { Panel } from "@/components/ui";

const CRM_ACTIVITIES = [
  { id: 1, type: "email_sent", title: "Outreach Email Delivered", lead: "MedCare Hospital", actor: "Ravi Rep (Sales Exec)", time: "2 hours ago", desc: "Sent personalized email draft citing Apollo Hospitals expansion news." },
  { id: 2, type: "ai_research", title: "AI Lead Research Generated", lead: "Northwind Logistics", actor: "Research Agent v1", time: "5 hours ago", desc: "TinyFish web search derived 3 claims and coverage score 0.85." },
  { id: 3, type: "meeting_booked", title: "Demo Meeting Booked", lead: "Brightpath Learning", actor: "Meeting Scheduler Agent", time: "1 day ago", desc: "Slot confirmed for Tuesday at 14:00 IST (08:30 UTC)." },
  { id: 4, type: "stage_change", title: "Deal Stage Updated", lead: "Cobalt Fintech", actor: "Manoj Manager", time: "2 days ago", desc: "Moved deal from Discovery → Qualified ($210,000 USD)." },
  { id: 5, type: "note", title: "Sales Rep Note Logged", lead: "Ferrovia Manufacturing", actor: "Ravi Rep", time: "3 days ago", desc: "Discussed trade show follow-up with primary contact." },
];

export default function CRMPage() {
  const [noteText, setNoteText] = useState("");
  const [selectedLead, setSelectedLead] = useState("MedCare Hospital");
  const [logs, setLogs] = useState(CRM_ACTIVITIES);

  function handleAddNote(e: React.FormEvent) {
    e.preventDefault();
    if (!noteText) return;
    const newNote = {
      id: Date.now(),
      type: "note",
      title: "Human Note Logged",
      lead: selectedLead,
      actor: "Ravi Rep (You)",
      time: "Just now",
      desc: noteText,
    };
    setLogs([newNote, ...logs]);
    setNoteText("");
  }

  return (
    <div className="space-y-8">
      <div>
        <div className="flex items-center gap-2 text-xs text-indigo-400 font-mono">
          <span>CRM & SALES WORKSPACE</span> <span>/</span> <span>ACTIVITIES & TIMELINE</span>
        </div>
        <h1 className="font-display text-3xl font-bold text-white tracking-tight mt-1">
          Unified CRM Activity Timeline
        </h1>
        <p className="text-sm text-slate-400 mt-1 max-w-2xl">
          Chronological story of all human actions, AI intelligence runs, stage changes, and meeting events. Activities are append-only to preserve audit integrity.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Timeline Column */}
        <div className="lg:col-span-2 space-y-6">
          <Panel title="Recent Unified Timeline" subtitle="Append-only activity stream across all assigned leads">
            <div className="relative border-l border-slate-800 ml-4 space-y-6 pl-6 pt-2">
              {logs.map((act) => (
                <div key={act.id} className="relative group">
                  {/* Timeline Dot */}
                  <span className="absolute -left-[31px] top-1 h-3.5 w-3.5 rounded-full bg-slate-900 border-2 border-indigo-400 shadow-sm shadow-indigo-400" />

                  <div className="glass-panel p-4 rounded-2xl border border-slate-800 hover:border-slate-700 transition-colors">
                    <div className="flex items-center justify-between">
                      <h3 className="font-semibold text-white text-sm">{act.title}</h3>
                      <span className="text-[11px] text-slate-500 font-mono">{act.time}</span>
                    </div>

                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs font-medium text-indigo-300 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20">
                        {act.lead}
                      </span>
                      <span className="text-xs text-slate-400">• {act.actor}</span>
                    </div>

                    <p className="mt-2 text-xs text-slate-300 leading-relaxed bg-slate-900/50 p-2.5 rounded-xl border border-slate-800/80">
                      {act.desc}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        {/* Right Col: Add Note & CRM Controls */}
        <div className="space-y-6">
          <Panel title="Log Human Note" subtitle="Notes are author-owned per crm_service.py">
            <form onSubmit={handleAddNote} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Select Prospect Lead</label>
                <select
                  value={selectedLead}
                  onChange={(e) => setSelectedLead(e.target.value)}
                  className="w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
                >
                  <option>MedCare Hospital</option>
                  <option>Northwind Logistics</option>
                  <option>Brightpath Learning</option>
                  <option>Ferrovia Manufacturing</option>
                  <option>Cobalt Fintech</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Note Content</label>
                <textarea
                  rows={4}
                  value={noteText}
                  onChange={(e) => setNoteText(e.target.value)}
                  placeholder="Record call summary, buyer feedback, or key objection notes..."
                  className="w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
                  required
                />
              </div>

              <button
                type="submit"
                className="w-full rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 py-2 text-xs font-semibold text-white shadow-lg shadow-indigo-500/20 hover:opacity-95 transition-all"
              >
                Log Activity Note
              </button>
            </form>
          </Panel>

          <Panel title="CRM Adapter Integration Status">
            <div className="space-y-3 text-xs">
              <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-900/60 border border-slate-800">
                <span className="font-semibold text-slate-200">Salesforce Adapter</span>
                <span className="text-amber-400 font-mono font-semibold">Stubbed (Local)</span>
              </div>
              <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-900/60 border border-slate-800">
                <span className="font-semibold text-slate-200">HubSpot Adapter</span>
                <span className="text-amber-400 font-mono font-semibold">Stubbed (Local)</span>
              </div>
              <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-900/60 border border-slate-800">
                <span className="font-semibold text-slate-200">Zoho CRM Adapter</span>
                <span className="text-amber-400 font-mono font-semibold">Stubbed (Local)</span>
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
