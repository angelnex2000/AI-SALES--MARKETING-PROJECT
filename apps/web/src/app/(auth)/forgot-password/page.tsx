"use client";

import { useState } from "react";
import Link from "next/link";

import api from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    // Backend always responds success (no user enumeration), so we can show
    // the confirmation regardless of outcome.
    try {
      await api.post("/auth/forgot-password", { email });
    } catch {
      /* intentionally ignored — never reveal whether the email exists */
    }
    setSent(true);
  }

  if (sent) {
    return (
      <div className="flex flex-col gap-4 text-center">
        <h1 className="text-xl font-semibold text-gray-900">Check your email</h1>
        <p className="text-sm text-gray-500">
          If an account exists for {email}, a reset link is on its way.
        </p>
        <Link href="/login" className="text-sm text-indigo-600 hover:underline">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Reset password</h1>
        <p className="mt-1 text-sm text-gray-500">We&apos;ll email you a reset link.</p>
      </div>
      <label className="flex flex-col gap-1 text-sm text-gray-700">
        Email
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm outline-none focus:border-gray-500"
        />
      </label>
      <button
        type="submit"
        className="mt-2 rounded-md bg-gray-900 py-2 text-sm font-medium text-white hover:bg-gray-800"
      >
        Send reset link
      </button>
      <Link href="/login" className="text-center text-sm text-indigo-600 hover:underline">
        Back to sign in
      </Link>
    </form>
  );
}
