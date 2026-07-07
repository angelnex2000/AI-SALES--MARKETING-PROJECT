import axios from "axios";

// Auth is an httpOnly cookie (set by POST /auth/login), not a token in
// localStorage — that's what lets middleware.ts read the role server-side
// while keeping the token itself invisible to client-side JS (XSS
// mitigation). withCredentials sends it automatically; there is nothing
// for this client to attach manually.
const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  withCredentials: true,
});

export default api;
