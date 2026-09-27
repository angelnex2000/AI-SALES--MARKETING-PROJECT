import { canAccess } from "@/lib/auth";
import { useAuthStore } from "@/store/authStore";
import type { Role } from "@/types";

/**
 * Convenience for role checks in components. Reads the role straight off the
 * auth store (no fetch side effect — the app layout already loads the user).
 * `can(roles)` mirrors the backend allow-lists. Frontend hiding only — the
 * real gate is require_role() on the API.
 */
export function useRole() {
  const role = useAuthStore((s) => s.user?.role ?? null);
  return {
    role,
    can: (roles: Role[]) => (role ? canAccess(role, roles) : false),
  };
}
