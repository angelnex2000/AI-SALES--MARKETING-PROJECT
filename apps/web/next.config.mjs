/**
 * @type {import('next').NextConfig}
 *
 * Same-origin proxy: the browser calls /api/* on :3000 and Next rewrites to
 * the FastAPI backend (NEXT_PUBLIC_API_URL, which includes /api/v1). This
 * keeps the httpOnly auth cookie first-party to :3000 — a SameSite=Lax cookie
 * would not be sent on a cross-origin XHR straight to :8000.
 *
 * NOTE: Next 14 does not support next.config.ts — must be .mjs/.js.
 */
const rawApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const apiBaseUrl = rawApiUrl.replace(/\/$/, "");
const versionedApiUrl = apiBaseUrl.endsWith("/api/v1") ? apiBaseUrl : `${apiBaseUrl}/api/v1`;

const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${versionedApiUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
