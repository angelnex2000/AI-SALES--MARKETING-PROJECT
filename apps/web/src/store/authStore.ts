import { create } from "zustand";

import api from "@/lib/api";
import type { Role, User } from "@/types";

interface AuthState {
  user: User | null;
  isLoading: boolean;
  login: (credentials: { email: string; password: string }) => Promise<void>;
  fetchCurrentUser: () => Promise<void>;
  logout: () => Promise<void>;
}

// Mock-first (Phase 6): if NEXT_PUBLIC_MOCK_ROLE is set, seed a fake
// authenticated user instead of calling the backend, so pages render (and the
// protected-route guard passes) without a running API. Change the role to test
// RBAC. Unset it for real cookie auth.
const MOCK_ROLE = process.env.NEXT_PUBLIC_MOCK_ROLE as Role | undefined;

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: true,
  login: async (credentials) => {
    const { data } = await api.post<{ user: User }>("/auth/login", credentials);
    set({ user: data.user, isLoading: false });
  },
  fetchCurrentUser: async () => {
    if (MOCK_ROLE) {
      set({
        user: {
          id: "mock-user",
          full_name: "Demo User",
          email: "demo@cloudcrm.ai",
          role: MOCK_ROLE,
          company_id: "mock-company",
        },
        isLoading: false,
      });
      return;
    }
    try {
      const { data } = await api.get<User>("/auth/me");
      set({ user: data, isLoading: false });
    } catch {
      set({ user: null, isLoading: false });
    }
  },
  logout: async () => {
    if (!MOCK_ROLE) await api.post("/auth/logout");
    set({ user: null });
  },
}));
