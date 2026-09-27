interface AsyncBoundaryProps {
  loading: boolean;
  error: string | null;
  isEmpty?: boolean;
  loadingMessage?: string;
  emptyMessage?: string;
  children: React.ReactNode;
}

export default function AsyncBoundary({
  loading,
  error,
  isEmpty = false,
  loadingMessage = "Loading intelligence pipeline...",
  emptyMessage = "No data recorded for this view.",
  children,
}: AsyncBoundaryProps) {
  if (loading) {
    return (
      <div className="glass-panel rounded-2xl p-10 text-center">
        <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-indigo-500/10 border border-indigo-500/30 text-indigo-400 animate-spin mb-3">
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
        </div>
        <p className="text-sm font-medium text-slate-300">{loadingMessage}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="glass-panel rounded-2xl border-rose-500/30 bg-rose-500/10 p-8 text-center text-sm text-rose-300">
        <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-rose-500/20 text-rose-400">
          ⚠️
        </div>
        <p className="font-semibold">{error}</p>
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div className="glass-panel rounded-2xl border-dashed border-slate-800 p-10 text-center text-sm text-slate-400">
        <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-slate-800/60 text-slate-400">
          🔍
        </div>
        <p>{emptyMessage}</p>
      </div>
    );
  }

  return <>{children}</>;
}
