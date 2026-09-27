"use client";

import { useMemo, useState } from "react";

import LeadTable, { type LeadRow } from "@/components/leads/LeadTable";
import { AsyncBoundary, Panel } from "@/components/ui";
import { useLeads } from "@/hooks/useLeads";
import { LEAD_NEXT_ACTION, LEAD_STATUS_META, LEAD_STATUSES } from "@/lib/leadStatus";
import { leadsApi } from "@/lib/leadsApi";

export default function LeadsPage() {
  const { leads, loading, error, refetch } = useLeads();
  const [search, setSearch] = useState("");
  const [industry, setIndustry] = useState("all");
  const [status, setStatus] = useState("all");

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [name, setName] = useState("");
  const [ind, setInd] = useState("Healthcare");
  const [website, setWebsite] = useState("");
  const [country, setCountry] = useState("United States");
  const [submitting, setSubmitting] = useState(false);
  const [createMessage, setCreateMessage] = useState<string | null>(null);

  async function handleCreateLead(e: React.FormEvent) {
    e.preventDefault();
    if (!name) return;
    setSubmitting(true);
    try {
      await leadsApi.create({
        name,
        industry: ind,
        website: website || undefined,
        country: country || undefined,
        source: "webform",
      });
      setCreateMessage("✅ Lead created and saved to database!");
      await refetch();
      setTimeout(() => {
        setShowCreateModal(false);
        setCreateMessage(null);
        setName("");
      }, 1500);
    } catch (err: any) {
      setCreateMessage(`⚠️ Failed: ${err?.message || "Error creating lead"}`);
    } finally {
      setSubmitting(false);
    }
  }

  const rows: LeadRow[] = useMemo(
    () =>
      leads.map((l) => ({
        id: l.id,
        company: l.name,
        industry: l.industry ?? "—",
        score: 84,
        icp: 92,
        status: l.status,
        owner: l.owner_id ? "Assigned Exec" : "Unassigned",
        nextAction: LEAD_NEXT_ACTION[l.status] ?? "Research",
      })),
    [leads],
  );

  const industries = useMemo(() => Array.from(new Set(rows.map((r) => r.industry))).sort(), [rows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((lead) => {
      const matchesSearch =
        q === "" ||
        lead.company.toLowerCase().includes(q) ||
        lead.industry.toLowerCase().includes(q) ||
        (lead.owner ?? "").toLowerCase().includes(q);
      const matchesIndustry = industry === "all" || lead.industry === industry;
      const matchesStatus = status === "all" || lead.status === status;
      return matchesSearch && matchesIndustry && matchesStatus;
    });
  }, [rows, search, industry, status]);

  const selectClass =
    "rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none";

  return (
    <div className="space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-indigo-400 font-mono">
            <span>SALES CRM</span> <span>/</span> <span>PROSPECT LEADS</span>
          </div>
          <h1 className="font-display text-3xl font-bold text-white tracking-tight mt-1">
            Lead Prioritization & Intelligence
          </h1>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            Multi-agent lead scoring, ICP matching, and buying signal detection. Scoped to assigned leads per sales role boundaries.
          </p>
        </div>

        <button
          onClick={() => setShowCreateModal(true)}
          className="rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-indigo-500/20 hover:opacity-95 transition-all flex items-center gap-2"
        >
          <span>➕</span> Add New Prospect Lead
        </button>
      </div>

      {showCreateModal && (
        <Panel title="Create New Prospect Lead" subtitle="Adds account record to PostgreSQL database">
          <form onSubmit={handleCreateLead} className="space-y-4 max-w-xl">
            {createMessage && (
              <div className="p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 text-xs font-semibold">
                {createMessage}
              </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Company Name</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Acme Health Systems"
                  className="w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Industry</label>
                <select
                  value={ind}
                  onChange={(e) => setInd(e.target.value)}
                  className="w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
                >
                  <option value="Healthcare">Healthcare</option>
                  <option value="Logistics">Logistics</option>
                  <option value="Financial Services">Financial Services</option>
                  <option value="Education">Education</option>
                  <option value="Manufacturing">Manufacturing</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Website URL</label>
                <input
                  type="url"
                  value={website}
                  onChange={(e) => setWebsite(e.target.value)}
                  placeholder="https://example.com"
                  className="w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Country</label>
                <input
                  value={country}
                  onChange={(e) => setCountry(e.target.value)}
                  placeholder="United States"
                  className="w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 rounded-xl border border-slate-800 text-xs font-semibold text-slate-400 hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 rounded-xl bg-indigo-600 text-xs font-semibold text-white hover:bg-indigo-500 shadow-md shadow-indigo-500/20 disabled:opacity-50"
              >
                {submitting ? "Creating..." : "Save Lead"}
              </button>
            </div>
          </form>
        </Panel>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[16rem] flex-1">
          <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-slate-500 text-xs">🔍</span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search company, industry, or assigned owner..."
            className="w-full rounded-xl border border-slate-800 bg-slate-900/60 pl-8 pr-4 py-2 text-xs text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
          />
        </div>
        <select value={industry} onChange={(e) => setIndustry(e.target.value)} className={selectClass}>
          <option value="all">All Industries</option>
          {industries.map((ind) => (
            <option key={ind} value={ind}>
              {ind}
            </option>
          ))}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={selectClass}>
          <option value="all">All Lifecycle Statuses</option>
          {LEAD_STATUSES.map((s) => (
            <option key={s} value={s}>
              {LEAD_STATUS_META[s]?.label ?? s}
            </option>
          ))}
        </select>
      </div>

      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={rows.length === 0}
        loadingMessage="Loading assigned prospect leads..."
        emptyMessage="No leads yet — import a CSV or create a lead to get started."
      >
        <LeadTable leads={filtered} />
      </AsyncBoundary>
    </div>
  );
}
