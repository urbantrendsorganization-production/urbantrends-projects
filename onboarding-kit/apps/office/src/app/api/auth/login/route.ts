import { NextRequest, NextResponse } from "next/server";

import { API_URL, setAuthCookies, type TokenResponse } from "@/lib/auth";

/**
 * Login proxy. Forwards credentials to the Rust API, and on success stores the
 * returned tokens as httpOnly cookies so the browser never handles raw JWTs
 * (CLAUDE.md §12). Returns only non-sensitive session info to the client.
 */
export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: { code: "bad_request", message: "Invalid JSON body." } },
      { status: 400 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/api/v1/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { error: { code: "upstream_unreachable", message: "The API is unreachable." } },
      { status: 502 },
    );
  }

  const data = await upstream.json();
  if (!upstream.ok) {
    // Pass through the backend's generic error body, never inventing detail.
    return NextResponse.json(data, { status: upstream.status });
  }

  const tokens = data as TokenResponse;
  const res = NextResponse.json({
    role: tokens.role,
    user_id: tokens.user_id,
    tenant_id: tokens.tenant_id,
  });
  setAuthCookies(res, tokens);
  return res;
}
