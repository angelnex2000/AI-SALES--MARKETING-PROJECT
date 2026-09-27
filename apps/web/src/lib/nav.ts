import type { Role } from "@/types";

export interface NavItem {
  href: string;
  label: string;
  roles: Role[];
}

const ALL: Role[] = ["admin", "sales_manager", "sales_executive", "marketing"];

/**
 * Single source of truth for role → navigation. The Sidebar renders these
 * (hiding links a role can't use) and middleware.ts derives its allowed route
 * prefixes from the SAME list — so the two can never drift. Both are
 * convenience only; the backend require_role() is the real authorization
 * boundary. Mirrors the CLAUDE.md page-permission matrix.
 */
export const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", roles: ALL },
  { href: "/leads", label: "Leads", roles: ALL },
  { href: "/pipeline", label: "Pipeline", roles: ALL },
  { href: "/campaigns", label: "Campaigns", roles: ALL },
  { href: "/outreach", label: "Outreach", roles: ["sales_manager", "sales_executive", "marketing"] },
  { href: "/meetings", label: "Meetings", roles: ["admin", "sales_manager", "sales_executive"] },
  { href: "/analytics", label: "Analytics", roles: ALL },
  { href: "/team", label: "Team", roles: ["admin", "sales_manager"] },
  { href: "/settings", label: "Settings", roles: ["admin"] },
];

/** Route prefixes a role may reach — used by middleware.ts for redirects. */
export function allowedRoutesFor(role: Role): string[] {
  return NAV.filter((item) => item.roles.includes(role)).map((item) => item.href);
}
