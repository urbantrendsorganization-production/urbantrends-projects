import { NextRequest, NextResponse } from "next/server";

import { ACCESS_COOKIE, API_URL } from "@/lib/auth";

/**
 * Generic authenticated proxy to the Rust API. Client components call
 * `/api/proxy/<path>` and this handler attaches the httpOnly access cookie as a
 * Bearer token, so the browser JS never touches the raw JWT (CLAUDE.md §12).
 *
 * Only forwards read/queue/review calls the reviewer console needs; the backend
 * still enforces RBAC and tenant scoping regardless.
 */
async function forward(request: NextRequest, path: string[]): Promise<NextResponse> {
  const accessToken = request.cookies.get(ACCESS_COOKIE)?.value;
  if (!accessToken) {
    return NextResponse.json(
      { error: { code: "unauthorized", message: "No session." } },
      { status: 401 },
    );
  }

  const search = request.nextUrl.search;
  const url = `${API_URL}/api/v1/${path.map(encodeURIComponent).join("/")}${search}`;

  const init: RequestInit = {
    method: request.method,
    headers: {
      authorization: `Bearer ${accessToken}`,
      "content-type": "application/json",
    },
    cache: "no-store",
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }

  try {
    const upstream = await fetch(url, init);
    // Pass through binary (exports) or JSON transparently.
    const contentType = upstream.headers.get("content-type") ?? "application/json";
    if (contentType.includes("application/json")) {
      const text = await upstream.text();
      return new NextResponse(text || "null", {
        status: upstream.status,
        headers: { "content-type": "application/json" },
      });
    }
    const buf = await upstream.arrayBuffer();
    return new NextResponse(buf, {
      status: upstream.status,
      headers: {
        "content-type": contentType,
        "content-disposition": upstream.headers.get("content-disposition") ?? "",
      },
    });
  } catch {
    return NextResponse.json(
      { error: { code: "upstream_unreachable", message: "The API is unreachable." } },
      { status: 502 },
    );
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, ctx: Ctx) {
  return forward(request, (await ctx.params).path);
}
export async function POST(request: NextRequest, ctx: Ctx) {
  return forward(request, (await ctx.params).path);
}
export async function PATCH(request: NextRequest, ctx: Ctx) {
  return forward(request, (await ctx.params).path);
}
