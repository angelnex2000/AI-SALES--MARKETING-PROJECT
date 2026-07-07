import { useEffect } from "react";
import { useAuthStore } from "@/store/authStore";

export function useAuth() {
  const { user, isLoading, fetchCurrentUser, logout } = useAuthStore();

  useEffect(() => {
    if (!user && isLoading) fetchCurrentUser();
  }, [user, isLoading, fetchCurrentUser]);

  return { user, isLoading, logout };
}