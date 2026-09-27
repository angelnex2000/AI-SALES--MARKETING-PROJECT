import api from "@/lib/api";
import type { Role } from "@/types";

/**
 * Users service (app/routers/users.py, mounted at the API root — it owns
 * /users, /roles, and /permissions). Admin manages; Manager reads.
 *
 * There is no roles table: /roles and /permissions return hard-coded constants
 * for rendering dropdowns and hints. require_role() is the real boundary.
 */

export interface UserDTO {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  company_id: string;
  created_at: string;
}

/** Page → per-role access level ("full" | "read" | "assigned" | "none" | …). */
export type PermissionMatrix = Record<string, Record<Role, string>>;

export const usersApi = {
  list: async (): Promise<UserDTO[]> => (await api.get<UserDTO[]>("/users")).data,

  roles: async (): Promise<Role[]> => (await api.get<Role[]>("/roles")).data,

  permissions: async (): Promise<PermissionMatrix> => (await api.get<PermissionMatrix>("/permissions")).data,

  /** Invite — no password field; the user sets one via the verify-email flow. */
  invite: async (payload: { full_name: string; email: string; role: Role }): Promise<UserDTO> =>
    (await api.post<UserDTO>("/users", payload)).data,

  /** Soft delete — deactivates rather than removing, preserving the audit trail. */
  deactivate: async (userId: string): Promise<void> => {
    await api.delete(`/users/${userId}`);
  },
};
