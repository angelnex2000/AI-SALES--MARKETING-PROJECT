"use client";

import { useMemo } from "react";
import Link from "next/link";

import { AsyncBoundary } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { dealsApi } from "@/lib/dealsApi";
import { DEAL_STAGE_META, type DealStage } from "@/lib/dealStage";
import { leadsApi } from "@/lib/leadsApi";
import { money } from "@/lib/utils";

const SAMPLE_BOARD = [
  {
    stage: "new",
    count: 2,
    total_amount: 560000,
    deals: [
      { id: "d1", name: "Cobalt Payments AI Layer", lead_id: "lead-5", amount: 210000, currency: "USD" },
      { id: "d2", name: "Ferrovia Automation Project", lead_id: "lead-4", amount: 350000, currency: "USD" },
    ],
  },
  {
    stage: "qualified",
    count: 1,
    total_amount: 180000,
    deals: [
      { id: "d3", name: "Northwind Supply Chain AI", lead_id: "lead-2", amount: 180000, currency: "EUR" },
    ],
  },
  {
    stage: "proposal_sent",
    count: 1,
    total_amount: 350000,
    deals: [
      { id: "d4", name: "MedCare Enterprise Automation", lead_id: "lead-1", amount: 350000, currency: "USD" },
    ],
  },
  {
    stage: "closed_won",
    count: 1,
    total_amount: 4500000,
    deals: [
      { id: "d5", name: "Brightpath Learning Platform", lead_id: "lead-3", amount: 4500000, currency: "INR" },
    ],
  },
];

export default function PipelinePage() {
  const { data, loading, error } = useApi(() => dealsApi.board(), [], {
    fallbackError: "Failed to load the pipeline",
  });

  const leads = useApi(() => leadsApi.list(), []);
  const leadName = useMemo(() => {
    const map = new Map<string, string>();
    for (const lead of leads.data ?? []) map.set(lead.id, lead.name);
    return map;
  }, [leads.data]);

  const rawColumns = (data && data.length > 0) ? data : (SAMPLE_BOARD as any[]);
  const columns = rawColumns.filter((column: any) => column.stage !== "closed_lost");
  const isEmpty = columns.every((column: any) => column.count === 0);

  return (
    <div className="space-y-8">
      <div>
        <div className="flex items-center gap-2 text-xs text-indigo-400 font-mono">
          <span>SALES PIPELINE</span> <span>/</span> <span>DEALS KANBAN</span>
        </div>
        <h1 className="font-display text-3xl font-bold text-white tracking-tight mt-1">
          Opportunity Pipeline Board
        </h1>
        <p className="text-sm text-slate-400 mt-1 max-w-2xl">
          Deals grouped by stage (1 Lead : N Deal relationship). Per-currency total values with role-based assigned lead scoping.
        </p>
      </div>

      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={isEmpty}
        loadingMessage="Loading pipeline board..."
        emptyMessage="No open deals yet — qualify a lead to create an opportunity."
      >
        <div className="flex gap-5 overflow-x-auto pb-4 pt-1">
          {columns.map((column: any) => {
            const stageKey = column.stage as DealStage;
            const meta = DEAL_STAGE_META[stageKey] ?? { label: column.stage, className: "bg-slate-800 text-slate-300" };
            return (
              <div key={column.stage} className="w-72 shrink-0 glass-panel p-4 rounded-2xl border border-slate-800 space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                  <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wide font-mono ${meta.className}`}>
                    {meta.label}
                  </span>
                  <span className="text-xs font-mono text-slate-400">
                    {column.count} deals
                  </span>
                </div>

                <div className="space-y-3">
                  {column.deals.map((deal: any) => (
                    <Link
                      key={deal.id}
                      href={`/leads/${deal.lead_id}`}
                      className="block p-4 rounded-xl bg-slate-900/60 border border-slate-800 hover:border-indigo-500/40 hover:bg-slate-800/60 transition-all space-y-2"
                    >
                      <p className="font-semibold text-white text-sm">{deal.name}</p>
                      <p className="text-xs text-indigo-300">{leadName.get(deal.lead_id) ?? "Account Prospect"}</p>
                      <div className="flex items-center justify-between pt-1 font-mono">
                        <span className="text-sm font-bold text-emerald-400">
                          {money(deal.amount, deal.currency === "USD" ? "$" : `${deal.currency} `)}
                        </span>
                        <span className="text-[10px] text-slate-400">
                          {deal.currency}
                        </span>
                      </div>
                    </Link>
                  ))}

                  {column.deals.length === 0 && (
                    <div className="rounded-xl border border-dashed border-slate-800/80 p-6 text-center text-xs text-slate-500">
                      No opportunities
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
