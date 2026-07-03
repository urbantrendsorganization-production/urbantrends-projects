import { NextResponse } from "next/server";

// Server-side base URL for the Rust API. In the compose stack set
// `API_URL=http://api:8080`; locally it defaults to the exposed port.
const API_URL = process.env.API_URL ?? "http://localhost:8080";

/**
 * Thin proxy to the backend health endpoint. Keeping the call server-side avoids
 * CORS and mirrors the auth proxy pattern used from Phase 1 onward (CLAUDE.md §12).
 */
export async function GET() {
  try {
    const upstream = await fetch(`${API_URL}/api/v1/health`, {
      cache: "no-store",
    });
    const body = await upstream.json();
    return NextResponse.json(body, { status: upstream.status });
  } catch (error) {
    return NextResponse.json(
      {
        status: "unreachable",
        database: "unknown",
        message: error instanceof Error ? error.message : "unknown error",
      },
      { status: 502 },
    );
  }
}
