"use client";

import { useState } from "react";
import { Panel } from "@/components/ui";

const AUDIT_LOGS = [
  { id: "log-1", time: "2026-08-06 22:45:12", category: "security", action: "user.login", actor: "Asha Admin (admin@acmecorp.dev)", details: "Successful httpOnly JWT authentication from IP 127.0.0.1" },
  { id: "log-2", time: "2026-08-06 22:30:00", category: "business", action: "lead.assign", actor: "Manoj Manager", details: "Gate 1: Assigned MedCare Hospital to Ravi Rep" },
  { id: "log-3", time: "2026-08-06 21:15:40", category: "business", action: "outreach.approve", actor: "Ravi Rep", details: "Gate 2: Approved email draft #402 for Northwind Logistics" },
  { id: "log-4", time: "2026-08-06 20:02:11", category: "security", action: "role.check_failure", actor: "Meera Marketing", details: "Denied attempt to access /api/v1/ai/scoring-config" },
  { id: "log-5", time: "2026-08-06 18:40:00", category: "business", action: "rag.document_upload", actor: "Asha Admin", details: "Uploaded case study doc: CityCare Healthcare Case Study" },
];

export default function AuditLogsPage() {
  const [filter, setFilter] = useState<"all" | "security" | "business">("all");

  const filteredLogs = filter === "all" ? AUDIT_LOGS : AUDIT_LOGS.filter((l) => l.category === filter);

  return (
    <div className="space-y-8">
      <div>
        <div className="flex items-center gap-2 text-xs text-indigo-400 font-mono">
          <span>SETTINGS</span> <span>/</span> <span>AUDIT & SECURITY LOGS</span>
        </div>
        <h1 className="font-display text-3xl font-bold text-white tracking-tight mt-1">
          Unified Platform Audit Log
        </h1>
        <p className="text-sm text-slate-400 mt-1 max-w-2xl">
          Single append-only table recording security and business operations per app/services/audit_service.py.
        </p>
      </div>

      <Panel
        title="Audit Events"
        action={
          <div className="flex gap-2">
            <button
              onClick={() => setFilter("all")}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                filter === "all" ? "bg-indigo-600 text-white" : "bg-slate-900 text-slate-400"
              }`}
            >
              All
            </button>
            <button
              onClick={() => setFilter("security")}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                filter === "security" ? "bg-purple-600 text-white" : "bg-slate-900 text-slate-400"
              }`}
            >
              Security
            </button>
            <button
              onClick={() => setFilter("business")}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                filter === "business" ? "bg-emerald-600 text-white" : "bg-slate-900 text-slate-400"
              }`}
            >
              Business
            </button>
          </div>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="border-b border-slate-800 bg-slate-900/80 text-slate-400 uppercase font-mono">
              <tr>
                <th className="py-3 px-4">Timestamp (UTC)</th>
                <th className="py-3 px-4">Category</th>
                <th className="py-3 px-4">Action</th>
                <th className="py-3 px-4">Actor</th>
                <th className="py-3 px-4">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-sans">
              {filteredLogs.map((log) => (
                <tr key={log.id} className="hover:bg-slate-800/40 transition-colors">
                  <td className="py-3 px-4 font-mono text-slate-400">{log.time}</td>
                  <td className="py-3 px-4">
                    <span
                      className={`px-2 py-0.5 rounded uppercase font-mono text-[10px] font-bold ${
                        log.category === "security"
                          ? "bg-purple-500/20 text-purple-300 border border-purple-500/30"
                          : "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                      }`}
                    >
                      {log.category}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-mono font-semibold text-white">{log.action}</td>
                  <td className="py-3 px-4 text-slate-300">{log.actor}</td>
                  <td className="py-3 px-4 text-slate-400">{log.details}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
