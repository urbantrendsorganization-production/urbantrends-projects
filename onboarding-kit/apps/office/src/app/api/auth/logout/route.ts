import { NextRequest, NextResponse } from "next/server";

import { API_URL, REFRESH_COOKIE, clearAuthCookies } from "@/lib/auth";

/**
 * Logout proxy. Best-effort revokes the refresh token at the API, then clears
 * the cookies regardless of the upstream outcome.
 */
export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;

  if (refreshToken) {
    try {
      await fetch(`${API_URL}/api/v1/auth/logout`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: "no-store",
      });
    } catch {
      // Ignore: we clear local cookies either way.
    }
  }

  const res = new NextResponse(null, { status: 204 });
  clearAuthCookies(res);
  return res;
}
