import type { Role } from "@/types";

/** Frontend hiding is convenience — real enforcement is require_role() on
 * the backend. Used by Sidebar/nav components to hide links a role
 * shouldn't see; never used as the sole gate on a sensitive action. */
export function canAccess(role: Role, allowedRoles: Role[]): boolean {
  return allowedRoles.includes(role);
}