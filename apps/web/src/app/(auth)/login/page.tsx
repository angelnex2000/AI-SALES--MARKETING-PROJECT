"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { useAuthStore } from "@/store/authStore";

const DEMO_PRESETS = [
  { role: "Sales Executive", email: "exec@acmecorp.dev" },
  { role: "Sales Manager", email: "manager@acmecorp.dev" },
  { role: "Admin", email: "admin@acmecorp.dev" },
  { role: "Marketing", email: "marketing@acmecorp.dev" },
];

export default function LoginPage() {
  const router = useRouter();
  const login = useAuthStore((state) => state.login);
  const [email, setEmail] = useState("exec@acmecorp.dev");
  const [password, setPassword] = useState("DevPassw0rd!");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login({ email, password });
      router.push("/dashboard");
    } catch (err) {
      const message = (err as { message?: string })?.message ?? "Invalid email or password";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  function applyPreset(presetEmail: string) {
    setEmail(presetEmail);
    setPassword("DevPassw0rd!");
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      <div className="text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-tr from-indigo-500 to-purple-500 text-white font-bold text-xl shadow-lg shadow-indigo-500/30">
          🤖
        </div>
        <h1 className="font-display text-2xl font-bold text-white tracking-tight">AI Sales Teammate</h1>
        <p className="mt-1 text-xs text-slate-400">Sign in to your multi-agent sales workspace</p>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3.5 py-2.5 text-xs text-rose-300">
          ⚠️ {error}
        </div>
      )}

      {/* Quick Demo Presets */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-3">
        <p className="text-[11px] font-semibold text-indigo-300 uppercase tracking-wide mb-2 text-center">
          ⚡ Quick 1-Click Demo Login
        </p>
        <div className="grid grid-cols-2 gap-1.5">
          {DEMO_PRESETS.map((p) => (
            <button
              key={p.email}
              type="button"
              onClick={() => applyPreset(p.email)}
              className={`rounded-lg px-2.5 py-1.5 text-[11px] font-medium text-left transition-all border ${
                email === p.email
                  ? "bg-indigo-600/30 border-indigo-500 text-white font-semibold"
                  : "bg-slate-800/60 border-slate-700/60 text-slate-400 hover:text-slate-200"
              }`}
            >
              {p.role}
            </button>
          ))}
        </div>
      </div>

      <label className="flex flex-col gap-1 text-xs font-semibold text-slate-300">
        <span>Work Email</span>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-xl border border-slate-800 bg-slate-900/80 px-3.5 py-2 text-xs text-slate-100 placeholder-slate-500 outline-none focus:border-indigo-500"
        />
      </label>

      <label className="flex flex-col gap-1 text-xs font-semibold text-slate-300">
        <span>Password</span>
        <input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded-xl border border-slate-800 bg-slate-900/80 px-3.5 py-2 text-xs text-slate-100 placeholder-slate-500 outline-none focus:border-indigo-500 font-mono"
        />
      </label>

      <div className="-mt-1 flex items-center justify-between text-xs">
        <span className="text-[11px] text-slate-500">Demo Password: DevPassw0rd!</span>
        <Link href="/forgot-password" className="text-indigo-400 hover:underline">
          Forgot password?
        </Link>
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="mt-1 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 py-2.5 text-xs font-semibold text-white shadow-lg shadow-indigo-500/25 hover:opacity-95 disabled:opacity-60 transition-all"
      >
        {submitting ? "Authenticating session…" : "Sign in to Workspace"}
      </button>

      <p className="text-center text-xs text-slate-400">
        No account?{" "}
        <Link href="/signup" className="text-indigo-400 font-semibold hover:underline">
          Create a workspace
        </Link>
      </p>
    </form>
  );
}
