interface StatCardProps {
  title: string;
  value: string;
  subtitle?: string;
  icon?: React.ReactNode;
  trend?: string;
  trendUp?: boolean;
  accentColor?: "indigo" | "emerald" | "amber" | "cyan" | "purple";
}

export default function StatCard({
  title,
  value,
  subtitle,
  icon,
  trend,
  trendUp = true,
  accentColor = "indigo",
}: StatCardProps) {
  const accentGradients = {
    indigo: "from-indigo-500/10 to-indigo-500/0 border-indigo-500/20 text-indigo-400",
    emerald: "from-emerald-500/10 to-emerald-500/0 border-emerald-500/20 text-emerald-400",
    amber: "from-amber-500/10 to-amber-500/0 border-amber-500/20 text-amber-400",
    cyan: "from-cyan-500/10 to-cyan-500/0 border-cyan-500/20 text-cyan-400",
    purple: "from-purple-500/10 to-purple-500/0 border-purple-500/20 text-purple-400",
  };

  return (
    <div className={`glass-panel glass-panel-hover relative overflow-hidden rounded-2xl bg-gradient-to-b p-5 border ${accentGradients[accentColor]}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</span>
        {icon && (
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-800/80 border border-slate-700/50 shadow-inner">
            {icon}
          </div>
        )}
      </div>

      <div className="mt-3 flex items-baseline justify-between">
        <p className="font-display text-3xl font-bold tracking-tight text-white">{value}</p>
        {trend && (
          <span
            className={`inline-flex items-center text-xs font-medium px-2 py-0.5 rounded-full ${
              trendUp ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
            }`}
          >
            {trendUp ? "↑" : "↓"} {trend}
          </span>
        )}
      </div>

      {subtitle && <p className="mt-2 text-xs text-slate-400/90">{subtitle}</p>}
    </div>
  );
}
