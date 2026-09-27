export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center bg-slate-950 p-6 overflow-hidden">
      {/* Glow Effects */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 h-96 w-96 rounded-full bg-indigo-600/15 blur-[120px]" />
      <div className="absolute bottom-1/4 right-1/4 h-80 w-80 rounded-full bg-purple-600/10 blur-[100px]" />

      <div className="glass-panel relative z-10 w-full max-w-md rounded-3xl border border-slate-800 p-8 shadow-2xl shadow-indigo-500/10">
        {children}
      </div>
    </div>
  );
}
