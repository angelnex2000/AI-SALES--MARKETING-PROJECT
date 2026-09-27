/** Deal pipeline stages — mirrors the backend DealStage enum
 * (app/models/deal.py). Separate from LeadStatus: a lead is an account, a deal
 * is an opportunity against it (1 Lead : N Deal, Phase 5 Module 5 reversal). */
export type DealStage =
  | "new"
  | "qualified"
  | "demo_scheduled"
  | "proposal_sent"
  | "negotiation"
  | "closed_won"
  | "closed_lost";

export const DEAL_STAGE_META: Record<DealStage, { label: string; className: string }> = {
  new: { label: "New", className: "bg-gray-100 text-gray-700" },
  qualified: { label: "Qualified", className: "bg-sky-100 text-sky-700" },
  demo_scheduled: { label: "Demo Scheduled", className: "bg-violet-100 text-violet-700" },
  proposal_sent: { label: "Proposal Sent", className: "bg-amber-100 text-amber-700" },
  negotiation: { label: "Negotiation", className: "bg-orange-100 text-orange-700" },
  closed_won: { label: "Closed Won", className: "bg-green-100 text-green-700" },
  closed_lost: { label: "Closed Lost", className: "bg-red-100 text-red-700" },
};

export const DEAL_STAGES = Object.keys(DEAL_STAGE_META) as DealStage[];
