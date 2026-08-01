# CLAUDE.md — Sync Server (Rust · Axum)

The relay + persistence layer. Terminates WebSockets, groups connections into rooms,
applies/relays CRDT updates via Yrs, and persists state. **Read the root `../CLAUDE.md`
first** for the cross-cutting rules.

## Stack
- Rust + Axum (WebSocket handling).
- yrs 0.27 with `yrs::sync` (protocol + awareness in-crate; standalone y-sync is abandoned).
- PostgreSQL (snapshots + update log + version history), e.g. via sqlx.
- Redis for cross-instance pub/sub fan-out (multi-node only).

## Connection lifecycle (implement in this order)
1. **Authenticate the upgrade** — token via query param or first message → verify →
   authorize for the requested room. Reject otherwise.
2. **Register** the connection against the document id (room).
3. **Initial sync** — exchange state vectors, send only the missing updates (y-sync steps).
4. **Steady state** — receive update → apply to the room's Yrs replica → broadcast to other
   room members → persist.
5. **Awareness** — relay only. Never persist.
6. **On drop** — de-register; clear the client's awareness entry after a timeout.

## Server-specific rules
- **Keep a server-side Yrs replica per active room** so late joiners sync correctly.
- **Persist updates (append log) + periodic snapshots.** Awareness is never persisted.
- **Rate-limit and apply backpressure per connection** — one client must not be able to
  flood a room.
- **Validate updates server-side** (size / shape); never trust client-supplied ids blindly.
- **Scale later.** Single node first; add Redis pub/sub per-room channel (or sticky room
  routing) only when measured load requires it. Don't build distribution prematurely.

## Conventions
- `cargo fmt` + `cargo clippy --all-targets -- -D warnings` clean before done.
- Isolate concerns: sync protocol in `server/src/sync/`, transport in `server/src/ws/`,
  storage in `server/src/store/`.
- **No `unwrap()` / `expect()` in connection or room-handling paths** — return errors.

## Commands
`cargo run` · `cargo test` · `cargo clippy --all-targets -- -D warnings` · `cargo fmt --check`

## Don't
- Don't persist awareness / presence.
- Don't implement custom conflict resolution — Yrs owns convergence.
- Don't split a room across nodes without Redis fan-out.
