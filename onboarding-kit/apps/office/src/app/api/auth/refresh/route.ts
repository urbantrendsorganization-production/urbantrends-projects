import { NextRequest, NextResponse } from "next/server";

import {
  API_URL,
  REFRESH_COOKIE,
  clearAuthCookies,
  setAuthCookies,
  type TokenResponse,
} from "@/lib/auth";

/**
 * Refresh proxy. Reads the httpOnly refresh cookie, exchanges it at the API for
 * a rotated pair, and rewrites the cookies. On failure the cookies are cleared
 * so the client falls back to login.
 */
export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  if (!refreshToken) {
    return NextResponse.json(
      { error: { code: "unauthorized", message: "No session." } },
      { status: 401 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { error: { code: "upstream_unreachable", message: "The API is unreachable." } },
      { status: 502 },
    );
  }

  if (!upstream.ok) {
    const res = NextResponse.json(await upstream.json(), { status: upstream.status });
    clearAuthCookies(res);
    return res;
  }

  const tokens = (await upstream.json()) as TokenResponse;
  const res = NextResponse.json({
    role: tokens.role,
    user_id: tokens.user_id,
    tenant_id: tokens.tenant_id,
  });
  setAuthCookies(res, tokens);
  return res;
}
