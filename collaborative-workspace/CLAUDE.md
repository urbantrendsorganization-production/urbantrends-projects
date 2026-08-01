# CLAUDE.md — Real-Time Collaborative Canvas & Workspace

Multi-user live-editing canvas. Browser clients each hold a full CRDT replica of the
document (Yjs); a Rust/Axum server relays updates between clients and persists state
(Yrs). Clients never talk to each other directly — everything goes through the server.

Deep architecture lives in `docs/ARCHITECTURE.md`. **This file is operating context —
keep it short and specific, not a manual.**

## Repository layout
- `web/`    — Next.js + TypeScript client (Yjs doc, canvas rendering, presence UI). See `web/CLAUDE.md`.
- `server/` — Rust + Axum sync server (Yrs, y-sync, persistence, auth). See `server/CLAUDE.md`.
- `docs/`   — architecture & design references.

## Non-negotiable rules (apply everywhere)
1. **Render from CRDT state only.** The UI is a pure function of the Yjs doc. Never keep a
   parallel copy of document state in component/local state — that is the #1 desync bug.
2. **Presence is ephemeral.** Cursors, selections, and identity live in the Yjs *awareness*
   channel and are **never** written to Postgres.
3. **Conflict resolution belongs to the CRDT, not app code.** No manual locking, no
   hand-rolled last-write-wins, no custom merge logic on top of Yjs/Yrs. Model the data so
   the CRDT resolves it (per-object maps, per-property keys).
4. **Throttle + interpolate cursors.** Send at most one cursor update per animation frame;
   tween on the receiving side.
5. **Authenticate the WebSocket handshake.** Every room join is authenticated (token on
   upgrade) and authorized against the document. No anonymous room access.
6. **One shared model, one wire protocol** (Yjs ⇄ Yrs / y-sync). If you change the shared
   document shape or protocol, change both sides in the same PR.

## Environment
- **Data model:** `Y.Map` of objects keyed by id; per-property values. Presence via awareness.
- **Storage:** PostgreSQL (state snapshots as `bytea` + append-only update log + version
  history). Redis (pub/sub fan-out across server instances; ephemeral only).
- **Deploy:** Hetzner · Docker Compose · Caddy (TLS/WSS) · GitHub Actions → GHCR.

## Common commands
> Adjust to the real scripts once they exist.
- Client dev / build:   `cd web && npm run dev`  /  `npm run build`
- Client checks:        `cd web && npm run lint && npm run typecheck`
- Server run / test:    `cd server && cargo run`  /  `cargo test`
- Server checks:        `cd server && cargo clippy --all-targets -- -D warnings && cargo fmt --check`
- Full stack:           `docker compose up`

## Before reporting a task done
- Client changes: `lint` + `typecheck` pass.
- Server changes: `clippy` clean and `cargo test` green.
- Shared-shape changes: both sides updated **and** a two-client sync smoke test still converges.

## Don't
- Don't introduce a second source of truth for document state.
- Don't persist awareness / presence data.
- Don't hand-roll OT or custom conflict resolution — the CRDT owns convergence.
- Don't add heavy dependencies to the hot sync path without discussion.
