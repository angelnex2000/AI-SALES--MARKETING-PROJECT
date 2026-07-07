import { NextRequest, NextResponse } from "next/server";
import type { Role } from "@/types";

// Convenience only — the real authorization boundary is require_role() in
// the FastAPI backend (see apps/api/app/dependencies/auth.py). This just
// avoids flashing a page the backend would reject anyway.
const ROLE_ACCESS: Record<Role, string[]> = {
  admin: ["/dashboard", "/team", "/settings", "/leads", "/campaigns", "/analytics"],
  sales_manager: ["/dashboard", "/leads", "/pipeline", "/analytics", "/campaigns", "/team"],
  sales_executive: ["/dashboard", "/leads", "/outreach", "/meetings"],
  marketing: ["/dashboard", "/campaigns", "/analytics", "/leads"],
};

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
  const token = request.cookies.get("access_token")?.value;

  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const role = decodeRole(token);
  const allowedPrefixes = role ? ROLE_ACCESS[role] : [];
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