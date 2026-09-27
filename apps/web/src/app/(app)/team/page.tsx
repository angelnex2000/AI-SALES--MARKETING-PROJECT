"use client";

import { useState } from "react";
import RequireRole from "@/components/auth/RequireRole";
import { AsyncBoundary, Panel } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { usersApi } from "@/lib/usersApi";
import type { Role } from "@/types";

const ROLE_BADGES: Record<Role, { label: string; badge: string }> = {
  admin: { label: "Admin", badge: "bg-purple-500/20 text-purple-300 border-purple-500/30" },
  sales_manager: { label: "Sales Manager", badge: "bg-blue-500/20 text-blue-300 border-blue-500/30" },
  sales_executive: { label: "Sales Executive", badge: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" },
  marketing: { label: "Marketing Executive", badge: "bg-amber-500/20 text-amber-300 border-amber-500/30" },
};

export default function TeamPage() {
  const { data, loading, error } = useApi(() => usersApi.list(), [], {
    fallbackError: "Failed to load the team",
  });
  const members = data ?? [];

  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("sales_executive");
  const [invitedMessage, setInvitedMessage] = useState(false);

  function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!inviteEmail || !inviteName) return;
    setInvitedMessage(true);
    setTimeout(() => {
      setShowInviteModal(false);
      setInvitedMessage(false);
      setInviteEmail("");
      setInviteName("");
    }, 2000);
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-indigo-400 font-mono">
            <span>COMPANY WORKSPACE</span> <span>/</span> <span>TEAM MEMBERS</span>
          </div>
          <h1 className="font-display text-3xl font-bold text-white tracking-tight mt-1">
            Team Members & Role Access Control
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Manage multi-tenant workspace members and enforce RBAC access boundaries.
          </p>
        </div>

        <RequireRole roles={["admin"]}>
          <button
            onClick={() => setShowInviteModal(true)}
            className="rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-indigo-500/20 hover:opacity-95 transition-all flex items-center gap-2"
          >
            <span>➕</span> Invite New Member
          </button>
        </RequireRole>
      </div>

      {showInviteModal && (
        <Panel title="Invite Team Member" subtitle="Send an onboarding invitation link with assigned role permissions">
          <form onSubmit={handleInvite} className="space-y-4 max-w-xl">
            {invitedMessage && (
              <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs font-semibold">
                ✅ Invitation sent to {inviteEmail}!
              </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Full Name</label>
                <input
                  value={inviteName}
                  onChange={(e) => setInviteName(e.target.value)}
                  placeholder="e.g. Priya Sales"
                  className="w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Work Email</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="priya@acmecorp.dev"
                  className="w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Assign System Role</label>
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as Role)}
                className="w-full rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
              >
                <option value="sales_executive">Sales Executive (Assigned Leads Only, Gate 2 Send)</option>
                <option value="sales_manager">Sales Manager (Gate 1 Lead Assignment, Analytics, Approvals)</option>
                <option value="marketing">Marketing Executive (Campaign Studio, Outreach Drafting)</option>
                <option value="admin">Admin (Full System Config, Integrations, Billing)</option>
              </select>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowInviteModal(false)}
                className="px-4 py-2 rounded-xl border border-slate-800 text-xs font-semibold text-slate-400 hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-2 rounded-xl bg-indigo-600 text-xs font-semibold text-white hover:bg-indigo-500 shadow-md shadow-indigo-500/20"
              >
                Send Invite Link
              </button>
            </div>
          </form>
        </Panel>
      )}

      <AsyncBoundary
        loading={loading}
        error={error}
        isEmpty={members.length === 0}
        loadingMessage="Loading team workspace..."
        emptyMessage="No members found."
      >
        <Panel title="Active Workspace Team">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="border-b border-slate-800 bg-slate-900/80 text-slate-400 uppercase font-mono">
                <tr>
                  <th className="py-3 px-4">Member Name</th>
                  <th className="py-3 px-4">Email</th>
                  <th className="py-3 px-4">System Role</th>
                  <th className="py-3 px-4 text-right">Account Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-sans">
                {members.map((m) => {
                  const roleMeta = ROLE_BADGES[m.role] ?? { label: m.role, badge: "bg-slate-800 text-slate-300" };
                  return (
                    <tr key={m.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="py-3.5 px-4 font-semibold text-white flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-tr from-indigo-500 to-purple-500 text-white font-bold text-xs">
                          {m.full_name ? m.full_name[0] : "U"}
                        </div>
                        {m.full_name}
                      </td>
                      <td className="py-3.5 px-4 text-slate-400 font-mono">{m.email}</td>
                      <td className="py-3.5 px-4">
                        <span className={`px-2.5 py-1 rounded-lg border text-[11px] font-medium ${roleMeta.badge}`}>
                          {roleMeta.label}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-right">
                        <span
                          className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${
                            m.is_active
                              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                              : "bg-slate-800 text-slate-500"
                          }`}
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-current" />
                          {m.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      </AsyncBoundary>
    </div>
  );
}
