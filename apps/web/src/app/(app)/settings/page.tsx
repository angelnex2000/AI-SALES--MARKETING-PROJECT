import Link from "next/link";

const sections = [
  { href: "/settings/integrations", title: "Integrations", desc: "CRM, email, calendar, and chat connections." },
  { href: "/settings/billing", title: "Billing", desc: "Plan, usage, and invoices." },
  { href: "/settings/ai-config", title: "AI Center", desc: "Agent health, model registry, scoring weights." },
  { href: "/settings/audit-logs", title: "Audit Logs", desc: "Security and business event history." },
  { href: "/team", title: "Team", desc: "Members and roles." },
];

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2 text-xs text-indigo-400 font-mono">
          <span>WORKSPACE</span> <span>/</span> <span>SETTINGS</span>
        </div>
        <h1 className="font-display text-3xl font-bold text-white tracking-tight mt-1">
          Settings & Configuration
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Manage your AI agent controls, integrations, billing plans, audit logs, and team access.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {sections.map((s) => (
          <Link
            key={s.href}
            href={s.href}
            className="glass-panel glass-panel-hover rounded-2xl border border-slate-800 p-5 space-y-2 transition-all"
          >
            <h2 className="text-base font-bold text-white font-display flex items-center justify-between">
              <span>{s.title}</span>
              <span className="text-xs text-indigo-400">→</span>
            </h2>
            <p className="text-xs text-slate-300 leading-relaxed">{s.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
