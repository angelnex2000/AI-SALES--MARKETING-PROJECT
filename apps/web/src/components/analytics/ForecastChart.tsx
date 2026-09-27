interface Point {
  month: string;
  value: number;
}

export default function ForecastChart({ data }: { data: Point[] }) {
  const max = Math.max(...data.map((d) => d.value), 1);

  return (
    <figure aria-label="Monthly revenue forecast" className="m-0 space-y-3">
      <div className="flex h-56 items-end gap-4 border-b border-slate-800 pb-2 px-4">
        {data.map((d) => {
          const heightPercent = Math.max((d.value / max) * 100, 8);
          return (
            <div key={d.month} className="group relative flex flex-1 flex-col items-center justify-end h-full">
              <span className="mb-2 text-xs font-mono font-bold text-indigo-300 opacity-90 group-hover:scale-110 transition-transform">
                ${(d.value / 1000).toFixed(0)}K
              </span>
              <div
                className="w-full rounded-t-xl bg-gradient-to-t from-indigo-600/40 via-indigo-500 to-purple-400 group-hover:from-indigo-500 group-hover:to-cyan-400 transition-all duration-300 shadow-lg shadow-indigo-500/20"
                style={{ height: `${heightPercent}%` }}
              />
            </div>
          );
        })}
      </div>
      <div className="flex gap-4 px-4 font-mono">
        {data.map((d) => (
          <span key={d.month} className="flex-1 text-center text-xs text-slate-400">
            {d.month}
          </span>
        ))}
      </div>
    </figure>
  );
}
