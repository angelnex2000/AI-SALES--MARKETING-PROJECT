import { create } from "zustand";
import api from "@/lib/api";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  isLoading: boolean;
  fetchCurrentUser: () => Promise<void>;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: true,
  fetchCurrentUser: async () => {
    try {
      const { data } = await api.get<User>("/auth/me");
      set({ user: data, isLoading: false });
    } catch {
      set({ user: null, isLoading: false });
    }
  },
  logout: async () => {
    await api.post("/auth/logout");
    set({ user: null });
  },
}));