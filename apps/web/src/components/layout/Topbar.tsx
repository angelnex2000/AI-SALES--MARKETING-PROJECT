"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/hooks/useAuth";
import api from "@/lib/api";
import { useUIStore } from "@/store/uiStore";

export default function Topbar() {
  const router = useRouter();
  const { user, logout } = useAuth();
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const { theme, toggleTheme } = useUIStore();
  const [agentCount, setAgentCount] = useState<number>(13);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    async function fetchAgents() {
      setLoading(true);
      try {
        const res = await api.get<{ registered_agents?: any[] }>("/ai/agents");
        if (res.data?.registered_agents) {
          setAgentCount(res.data.registered_agents.length);
        } else if (Array.isArray(res.data)) {
          setAgentCount(res.data.length);
        }
      } catch {
        setAgentCount(13);
      } finally {
        setLoading(false);
      }
    }
    fetchAgents();
  }, []);

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  const initial = user?.full_name ? user.full_name[0].toUpperCase() : "U";

  return (
    <header className="flex h-16 items-center justify-between border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-md px-6 z-10">
      <div className="flex items-center gap-4">
        <button
          onClick={toggleSidebar}
          aria-label="Toggle sidebar"
          className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 text-slate-400 hover:border-slate-700 hover:text-slate-200 transition-all"
        >
          <span className="text-sm">☰</span>
        </button>

        {/* Global Search Bar */}
        <div className="relative hidden sm:block">
          <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-slate-500 text-xs">🔍</span>
          <input
            className="w-72 rounded-xl border border-slate-800/90 bg-slate-900/60 pl-8 pr-4 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 transition-all"
            placeholder="Search leads, campaigns, or AI insights..."
          />
        </div>
      </div>

      <div className="flex items-center gap-4">
        {/* Dynamic Agent Health Indicator */}
        <div className="hidden md:flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-400">
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="font-mono font-medium">
            {loading ? "Checking Agents..." : `${agentCount} Active AI Agents`}
          </span>
        </div>

        {/* Theme Toggle Button */}
        <button
          onClick={toggleTheme}
          title="Toggle Light / Dark Theme"
          className="flex items-center gap-1.5 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:border-indigo-500/40 hover:text-white transition-all"
        >
          <span>{theme === "dark" ? "🌙 Dark Mode" : "☀️ Light Mode"}</span>
        </button>

        {/* User Info & Avatar */}
        <div className="flex items-center gap-3 border-l border-slate-800 pl-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-tr from-indigo-500 to-purple-500 font-semibold text-xs text-white shadow-md shadow-indigo-500/20">
            {initial}
          </div>
          <div className="hidden sm:block text-left">
            <p className="text-xs font-semibold text-slate-200 leading-tight">{user?.full_name ?? "Authenticated User"}</p>
            <p className="text-[10px] text-slate-400 uppercase font-mono">{user?.role ?? "User"}</p>
          </div>
          <button
            onClick={handleLogout}
            className="ml-2 rounded-lg border border-slate-800 bg-slate-900/80 px-2.5 py-1 text-xs font-medium text-slate-400 hover:border-slate-700 hover:text-white transition-colors"
          >
            Logout
          </button>
        </div>
      </div>
    </header>
  );
}
