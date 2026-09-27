"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import api from "@/lib/api";

function Verify() {
  const token = useSearchParams().get("token") ?? "";
  const [status, setStatus] = useState<"verifying" | "ok" | "error">("verifying");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      return;
    }
    api
      .post("/auth/verify-email", null, { params: { token } })
      .then(() => setStatus("ok"))
      .catch(() => setStatus("error"));
  }, [token]);

  const copy = {
    verifying: "Verifying your email…",
    ok: "Your email is verified. You can sign in now.",
    error: "This verification link is invalid or expired.",
  }[status];

  return (
    <div className="flex flex-col gap-4 text-center">
      <h1 className="text-xl font-semibold text-gray-900">Email verification</h1>
      <p className="text-sm text-gray-500">{copy}</p>
      {status !== "verifying" && (
        <Link href="/login" className="text-sm text-indigo-600 hover:underline">
          Back to sign in
        </Link>
      )}
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<p className="text-sm text-gray-500">Loading…</p>}>
      <Verify />
    </Suspense>
  );
}
