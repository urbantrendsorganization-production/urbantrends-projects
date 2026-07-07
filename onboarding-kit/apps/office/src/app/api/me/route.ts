import { NextRequest, NextResponse } from "next/server";

import { ACCESS_COOKIE, API_URL } from "@/lib/auth";

/**
 * Session probe. Forwards the httpOnly access cookie as a Bearer token to the
 * API's /me endpoint so the client can learn who is logged in without ever
 * reading the token itself.
 */
export async function GET(request: NextRequest) {
  const accessToken = request.cookies.get(ACCESS_COOKIE)?.value;
  if (!accessToken) {
    return NextResponse.json(
      { error: { code: "unauthorized", message: "No session." } },
      { status: 401 },
    );
  }

  try {
    const upstream = await fetch(`${API_URL}/api/v1/me`, {
      headers: { authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { error: { code: "upstream_unreachable", message: "The API is unreachable." } },
      { status: 502 },
    );
  }
}
