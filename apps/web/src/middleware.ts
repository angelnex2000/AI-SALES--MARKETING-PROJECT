import { NextRequest, NextResponse } from "next/server";

import { allowedRoutesFor } from "@/lib/nav";
import type { Role } from "@/types";

// Mock-first: with NEXT_PUBLIC_MOCK_ROLE set there is no real auth cookie (the
// client seeds a mock user instead), so skip the guard entirely. Unset it to
// enforce real cookie auth against the backend.
const MOCK_ROLE = process.env.NEXT_PUBLIC_MOCK_ROLE;

// Convenience only — the real authorization boundary is require_role() in the
// FastAPI backend. Allowed prefixes derive from the shared NAV list (lib/nav)
// so this can never drift from the sidebar.
function decodeRole(token: string): Role | null {
  try {
    const base64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(base64));
    return payload.role ?? null;
  } catch {
    return null;
  }
}

export function middleware(request: NextRequest) {
  if (MOCK_ROLE) return NextResponse.next();

  const token = request.cookies.get("access_token")?.value;
  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const role = decodeRole(token);
  const allowedPrefixes = role ? allowedRoutesFor(role) : [];
  const isAllowed = allowedPrefixes.some((prefix) => request.nextUrl.pathname.startsWith(prefix));

  if (!isAllowed) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/leads/:path*",
    "/campaigns/:path*",
    "/outreach/:path*",
    "/meetings/:path*",
    "/crm/:path*",
    "/analytics/:path*",
    "/pipeline/:path*",
    "/forecast/:path*",
    "/team/:path*",
    "/settings/:path*",
  ],
};
