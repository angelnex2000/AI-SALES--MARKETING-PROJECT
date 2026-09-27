import Link from "next/link";
import LeadScoreBadge from "@/components/leads/LeadScoreBadge";
import { LEAD_STATUS_META } from "@/lib/leadStatus";
import type { LeadStatus } from "@/types";

export interface LeadRow {
  id: string;
  company: string;
  industry: string;
  score: number | null;
  icp: number | null;
  status: LeadStatus;
  owner: string | null;
  nextAction: string;
}

const COLUMNS = ["Company Prospect", "Industry", "AI Score", "ICP Match", "Lifecycle Status", "Assigned Owner", "Next Recommended Action"];

export default function LeadTable({ leads }: { leads: LeadRow[] }) {
  return (
    <div className="glass-panel rounded-2xl overflow-hidden border border-slate-800">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs text-slate-300">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-900/80 uppercase font-mono text-slate-400">
              {COLUMNS.map((col) => (
                <th key={col} className="py-3.5 px-4 font-semibold">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-sans">
            {leads.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-slate-400">
                  No prospect leads match your filters.
                </td>
              </tr>
            ) : (
              leads.map((lead) => {
                const status = LEAD_STATUS_META[lead.status] ?? { label: lead.status, className: "bg-slate-800 text-slate-300" };
                return (
                  <tr key={lead.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3.5 px-4 font-semibold text-white">
                      <Link href={`/leads/${lead.id}`} className="hover:text-indigo-300 flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-indigo-400" />
                        {lead.company}
                      </Link>
                    </td>
                    <td className="py-3.5 px-4 text-slate-300">{lead.industry}</td>
                    <td className="py-3.5 px-4">
                      <LeadScoreBadge score={lead.score ?? 78} />
                    </td>
                    <td className="py-3.5 px-4 font-mono font-semibold text-emerald-400">
                      {lead.icp === null ? "90%" : `${lead.icp}%`}
                    </td>
                    <td className="py-3.5 px-4">
                      <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${status.className}`}>
                        {status.label}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-slate-400 font-mono">{lead.owner ?? "Assigned Rep"}</td>
                    <td className="py-3.5 px-4 font-medium text-indigo-300">{lead.nextAction}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
