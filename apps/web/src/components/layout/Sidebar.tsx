"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { canAccess } from "@/lib/auth";
import { NAV } from "@/lib/nav";
import { useUIStore } from "@/store/uiStore";
import type { Role } from "@/types";

const ROLE_LABELS: Record<Role, { label: string; badge: string }> = {
  admin: { label: "Admin Workspace", badge: "bg-purple-500/20 text-purple-300 border-purple-500/30" },
  sales_manager: { label: "Sales Manager", badge: "bg-blue-500/20 text-blue-300 border-blue-500/30" },
  sales_executive: { label: "Sales Executive", badge: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" },
  marketing: { label: "Marketing", badge: "bg-amber-500/20 text-amber-300 border-amber-500/30" },
};

const ICONS: Record<string, string> = {
  "/dashboard": "⚡",
  "/leads": "🎯",
  "/pipeline": "📊",
  "/campaigns": "🚀",
  "/outreach": "✉️",
  "/meetings": "📅",
  "/analytics": "📈",
  "/team": "👥",
  "/settings": "⚙️",
};

export default function Sidebar({ role }: { role?: Role }) {
  const pathname = usePathname();
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const items = role ? NAV.filter((item) => canAccess(role, item.roles)) : [];

  return (
    <aside
      className={`${
        collapsed ? "w-20" : "w-64"
      } shrink-0 bg-sidebar border-r border-slate-800/80 flex flex-col justify-between p-4 text-slate-300 transition-all duration-300 relative z-20`}
    >
      <div>
        {/* Brand Header */}
        <div className="flex items-center justify-between mb-6 px-2">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-purple-600 to-cyan-400 p-0.5 shadow-lg shadow-indigo-500/20 flex items-center justify-center font-bold text-white">
              <span className="text-lg">🤖</span>
            </div>
            {!collapsed && (
              <div>
                <h2 className="font-display font-bold text-white text-base tracking-wide flex items-center gap-1.5">
                  AI Sales <span className="text-xs bg-indigo-500/30 text-indigo-300 border border-indigo-500/40 px-1.5 py-0.5 rounded font-mono">3.0</span>
                </h2>
                <p className="text-[11px] text-slate-400">Multi-Agent Revenue SaaS</p>
              </div>
            )}
          </div>
        </div>

        {/* User Role Badge */}
        {!collapsed && role && (
          <div className="mb-5 px-2">
            <div className={`text-xs px-2.5 py-1 rounded-lg border flex items-center gap-1.5 font-medium ${ROLE_LABELS[role]?.badge ?? ""}`}>
              <span className="h-1.5 w-1.5 rounded-full bg-current animate-ping" />
              <span>{ROLE_LABELS[role]?.label ?? role}</span>
            </div>
          </div>
        )}

        {/* Navigation List */}
        <nav className="space-y-1">
          {items.map((item) => {
            const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(`${item.href}`));
            const icon = ICONS[item.href] || "📌";

            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.label}
                className={`group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200 ${
                  active
                    ? "bg-gradient-to-r from-indigo-600/30 to-purple-600/10 border border-indigo-500/30 text-white shadow-md shadow-indigo-500/10"
                    : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
                } ${collapsed ? "justify-center" : ""}`}
              >
                <span className="text-base group-hover:scale-110 transition-transform">{icon}</span>
                {!collapsed && <span>{item.label}</span>}
                {!collapsed && active && (
                  <span className="ml-auto h-2 w-2 rounded-full bg-indigo-400 shadow-sm shadow-indigo-400" />
                )}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Footer / System Status */}
      <div className="border-t border-slate-800/80 pt-4 mt-6 px-2">
        <button
          onClick={toggleSidebar}
          className="w-full flex items-center justify-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 py-2 text-xs font-medium text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
        >
          <span>{collapsed ? "⏩" : "⏪ Collapse Sidebar"}</span>
        </button>
      </div>
    </aside>
  );
}
