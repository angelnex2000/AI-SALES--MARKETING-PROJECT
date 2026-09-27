import axios from "axios";

// Auth is an httpOnly cookie (set by POST /api/v1/auth/login), not a token in
// localStorage — that's what lets middleware.ts read the role server-side
// while keeping the token itself invisible to client-side JS (XSS mitigation).
//
// baseURL is the SAME-ORIGIN "/api" path, not the backend URL directly:
// next.config.ts rewrites /api/* -> NEXT_PUBLIC_API_URL (which includes
// /api/v1). Going through the same origin keeps the cookie first-party to
// :3000 — a SameSite=Lax cookie would NOT be sent on a cross-origin XHR to
// :8000. withCredentials makes axios include it.
const api = axios.create({
  baseURL: "/api",
  withCredentials: true,
});

// Phase 5 wraps every response in { success, message, data }. Unwrap it here so
// call sites get the payload directly (res.data === the data field), and turn
// success:false into a rejected promise.
api.interceptors.response.use(
  (response) => {
    const body = response.data;
    if (body && typeof body === "object" && "success" in body) {
      if (!body.success) {
        return Promise.reject(body);
      }
      response.data = body.data;
    }
    return response;
  },
  (error) => Promise.reject(error),
);

export default api;
