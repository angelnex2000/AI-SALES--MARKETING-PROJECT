"use client";

import { useRole } from "@/hooks/useRole";
import type { Role } from "@/types";

/**
 * Renders `children` only if the current user's role is allowed; otherwise
 * `fallback` (default: nothing). Use to hide privileged actions — e.g. Gate 2
 * approve/send for Sales Exec, "Invite User" for Admin. This is UX only: the
 * backend still rejects the action for a wrong role.
 */
export default function RequireRole({
  roles,
  children,
  fallback = null,
}: {
  roles: Role[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const { can } = useRole();
  return <>{can(roles) ? children : fallback}</>;
}
