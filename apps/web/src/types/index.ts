export type Role = "admin" | "sales_manager" | "sales_executive" | "marketing";

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
}

export interface Lead {
  id: string;
  company: string;
  industry: string;
  employees: number;
  email: string;
  status: LeadStatus;
  score: number | null;
  assignedTo: string | null;
  icpMatch: number | null;
}

export type LeadStatus =
  | "new"
  | "researching"
  | "ready"
  | "contacted"
  | "demo_scheduled"
  | "proposal"
  | "closed_won"
  | "closed_lost";

export interface Campaign {
  id: string;
  name: string;
  industry: string;
  status: "draft" | "active" | "paused" | "completed";
}

export interface ReplyIntent {
  intent: "interested" | "follow_up" | "rejected" | "info_request";
  confidence: number;
  suggestedAction: string;
}
