"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import api from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [form, setForm] = useState({ company_name: "", full_name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const update = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      // Creates a new company workspace + first admin. Does NOT log in
      // (email verification required before first login), so send to /login.
      await api.post("/auth/signup", form);
      router.push("/login");
    } catch (err) {
      setError((err as { message?: string })?.message ?? "Signup failed");
    } finally {
      setSubmitting(false);
    }
  }

  const inputClass = "rounded-md border border-gray-300 px-3 py-2 text-sm outline-none focus:border-gray-500";

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Create your workspace</h1>
        <p className="mt-1 text-sm text-gray-500">You&apos;ll be the workspace admin.</p>
      </div>

      {error && <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      <label className="flex flex-col gap-1 text-sm text-gray-700">
        Company name
        <input required value={form.company_name} onChange={update("company_name")} className={inputClass} />
      </label>
      <label className="flex flex-col gap-1 text-sm text-gray-700">
        Full name
        <input required value={form.full_name} onChange={update("full_name")} className={inputClass} />
      </label>
      <label className="flex flex-col gap-1 text-sm text-gray-700">
        Email
        <input type="email" required value={form.email} onChange={update("email")} className={inputClass} />
      </label>
      <label className="flex flex-col gap-1 text-sm text-gray-700">
        Password
        <input type="password" required value={form.password} onChange={update("password")} className={inputClass} />
      </label>

      <button
        type="submit"
        disabled={submitting}
        className="mt-2 rounded-md bg-gray-900 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-60"
      >
        {submitting ? "Creating…" : "Create workspace"}
      </button>

      <p className="text-center text-sm text-gray-500">
        Already have an account?{" "}
        <Link href="/login" className="text-indigo-600 hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
