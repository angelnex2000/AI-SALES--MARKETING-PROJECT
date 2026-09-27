export default function LeadScoreBadge({ score }: { score: number | null }) {
  if (score === null || score === undefined) {
    return <span className="text-slate-500 font-mono">—</span>;
  }

  const tone =
    score >= 80
      ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30 shadow-sm shadow-emerald-500/10"
      : score >= 50
        ? "bg-amber-500/20 text-amber-300 border-amber-500/30 shadow-sm shadow-amber-500/10"
        : "bg-slate-800 text-slate-400 border-slate-700";

  return (
    <span className={`inline-flex min-w-[2.5rem] items-center justify-center rounded-full px-2.5 py-0.5 text-xs font-mono font-bold border ${tone}`}>
      {score}
    </span>
  );
}
