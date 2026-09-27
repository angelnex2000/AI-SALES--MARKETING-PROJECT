import type { LeadStatus } from "@/types";

/**
 * Display label + badge styling for each pipeline status. Single source of
 * truth so the Leads list, Lead Details, and Pipeline board all render a
 * status the same way. Keys are the exact backend `LeadStatus` enum values.
 */
export const LEAD_STATUS_META: Record<LeadStatus, { label: string; className: string }> = {
  new: { label: "New", className: "bg-gray-100 text-gray-700" },
  researching: { label: "Researching", className: "bg-sky-100 text-sky-700" },
  ready: { label: "Ready for Outreach", className: "bg-emerald-100 text-emerald-700" },
  contacted: { label: "Contacted", className: "bg-indigo-100 text-indigo-700" },
  demo_scheduled: { label: "Demo Scheduled", className: "bg-violet-100 text-violet-700" },
  proposal: { label: "Proposal", className: "bg-amber-100 text-amber-700" },
  closed_won: { label: "Closed Won", className: "bg-green-100 text-green-700" },
  closed_lost: { label: "Closed Lost", className: "bg-red-100 text-red-700" },
};

export const LEAD_STATUSES = Object.keys(LEAD_STATUS_META) as LeadStatus[];

/** Suggested next action per status — a UI hint (the list endpoint doesn't
 * carry one). */
export const LEAD_NEXT_ACTION: Record<LeadStatus, string> = {
  new: "Run AI Research",
  researching: "Awaiting research",
  ready: "Generate Outreach",
  contacted: "Follow Up",
  demo_scheduled: "Prepare Demo",
  proposal: "Send Proposal",
  closed_won: "—",
  closed_lost: "—",
};
