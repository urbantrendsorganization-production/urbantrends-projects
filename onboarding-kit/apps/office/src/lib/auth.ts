// Shared auth constants for the office console (CLAUDE.md §12).
//
// Tokens live in httpOnly cookies set by the route-handler proxy — never in
// client-readable storage — so the browser JS never touches the raw JWT.

import type { NextResponse } from "next/server";

/** Server-side base URL for the Rust API. */
export const API_URL = process.env.API_URL ?? "http://localhost:8080";

export const ACCESS_COOKIE = "ok_access";
export const REFRESH_COOKIE = "ok_refresh";

// Match the backend token TTLs (§7): access 15 min, refresh 14 days.
const ACCESS_MAX_AGE = 15 * 60;
const REFRESH_MAX_AGE = 14 * 24 * 60 * 60;

const isProd = process.env.NODE_ENV === "production";

/** The shape the backend returns from /auth/login and /auth/refresh. */
export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  role: "agent" | "reviewer" | "admin";
  user_id: string;
  tenant_id: string;
};

/** Write the access + refresh tokens as httpOnly cookies on a response. */
export function setAuthCookies(res: NextResponse, tokens: TokenResponse): void {
  const base = {
    httpOnly: true,
    secure: isProd,
    sameSite: "lax" as const,
    path: "/",
  };
  res.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    ...base,
    maxAge: ACCESS_MAX_AGE,
  });
  res.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
    ...base,
    maxAge: REFRESH_MAX_AGE,
  });
}

/** Remove both auth cookies (logout). */
export function clearAuthCookies(res: NextResponse): void {
  res.cookies.set(ACCESS_COOKIE, "", { path: "/", maxAge: 0 });
  res.cookies.set(REFRESH_COOKIE, "", { path: "/", maxAge: 0 });
}
