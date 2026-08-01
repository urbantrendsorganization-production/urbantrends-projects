/**
 * Presence: who is in the room, where their pointer is, and what they have selected.
 *
 * This is the *awareness* channel, not the document. Nothing here is ever written into the
 * `Y.Doc` or persisted — it exists only for as long as a socket is open. Selection in
 * particular is per-user UI state: it is mirrored into awareness so peers can see it, and
 * deliberately kept out of the shared `Y.Map`, where it would become everyone's selection.
 */
import type { Awareness } from "y-protocols/awareness";

export interface PresenceUser {
  readonly id: string;
  readonly name: string;
  readonly color: string;
}

export interface Point {
  readonly x: number;
  readonly y: number;
}

/** Exactly what a client publishes into the awareness channel. */
export interface PresenceState {
  readonly user: PresenceUser;
  /** `null` while the pointer is outside the canvas — an absent cursor, not a stale one. */
  readonly cursor: Point | null;
  readonly selection: readonly string[];
}

export interface Peer extends PresenceState {
  /** Yjs client id. Assigned per document replica, so it identifies the *connection*. */
  readonly clientId: number;
  readonly isLocal: boolean;
}

/** Identity fields only — the part of a peer that never changes while it is connected. */
export interface RosterEntry {
  readonly clientId: number;
  readonly user: PresenceUser;
  readonly isLocal: boolean;
}

/**
 * Chosen to stay legible against the canvas grid in both light and dark, and to be
 * distinguishable from each other at cursor size.
 */
const COLORS = [
  "#e5484d",
  "#f76b15",
  "#f5d90a",
  "#46a758",
  "#12a594",
  "#0090ff",
  "#7c66dc",
  "#d6409f",
] as const;

const ADJECTIVES = [
  "Swift",
  "Quiet",
  "Bright",
  "Brave",
  "Clever",
  "Gentle",
  "Bold",
  "Curious",
  "Nimble",
  "Sunny",
  "Keen",
  "Merry",
] as const;

const ANIMALS = [
  "Heron",
  "Otter",
  "Falcon",
  "Badger",
  "Lynx",
  "Marten",
  "Ibis",
  "Hare",
  "Kestrel",
  "Vole",
  "Osprey",
  "Fennec",
] as const;

/** A hostile or buggy peer must not be able to make us paint an unbounded list. */
const MAX_SELECTION = 512;

/** FNV-1a. Not cryptographic — this only needs to spread ids evenly across the tables. */
function hash(value: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < value.length; i += 1) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/**
 * Mints a throwaway identity from a Yjs client id. There is no login yet, so identity lives
 * exactly as long as the replica does.
 *
 * The client id is used as the seed rather than a fresh UUID because it already *is* the
 * stable per-connection identifier: Yjs assigns it randomly per replica and keeps it across
 * reconnects, so the name and colour survive a dropped socket instead of shuffling.
 *
 * Name and colour are *derived* from it rather than drawn separately, so they stay fixed
 * for the whole session. Independent slices of the hash keep the two from correlating.
 */
export function createIdentity(clientId: number): PresenceUser {
  const id = String(clientId);
  const h = hash(id);

  return {
    id,
    name: `${ADJECTIVES[h % ADJECTIVES.length]} ${ANIMALS[(h >>> 8) % ANIMALS.length]}`,
    color: COLORS[(h >>> 16) % COLORS.length],
  };
}

/** Two letters for a badge: "Swift Heron" → "SH". */
export function initials(name: string): string {
  const words = name.split(/\s+/).filter((word) => word.length > 0);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readUser(value: unknown): PresenceUser | null {
  if (!isRecord(value)) return null;
  const { id, name, color } = value;
  if (typeof id !== "string" || typeof name !== "string") return null;
  if (typeof color !== "string") return null;

  // Colours go straight into a canvas fillStyle, so only accept the exact literal shape we
  // publish rather than trusting a peer to send something sane.
  if (!/^#[0-9a-f]{6}$/i.test(color)) return null;

  return { id, name, color };
}

function readPoint(value: unknown): Point | null {
  if (!isRecord(value)) return null;
  const { x, y } = value;
  if (typeof x !== "number" || !Number.isFinite(x)) return null;
  if (typeof y !== "number" || !Number.isFinite(y)) return null;
  return { x, y };
}

function readSelection(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((id): id is string => typeof id === "string")
    .slice(0, MAX_SELECTION);
}

/**
 * Projects one raw awareness entry into a `PresenceState`, or `null` if it is not one.
 *
 * Awareness payloads arrive as untyped JSON from other clients, so every field is checked
 * rather than cast. A peer mid-handshake legitimately has no state yet, which is a normal
 * thing to skip.
 */
export function readPresence(value: unknown): PresenceState | null {
  if (!isRecord(value)) return null;

  const user = readUser(value.user);
  if (user === null) return null;

  return {
    user,
    cursor: readPoint(value.cursor),
    selection: readSelection(value.selection),
  };
}

/**
 * Everyone currently in the room, including us.
 *
 * Called at paint time — the result is a derived projection of the awareness channel and is
 * never stored. Sorted by client id so badges keep a stable order across renders.
 */
export function readPeers(awareness: Awareness): Peer[] {
  const local = awareness.clientID;
  const peers: Peer[] = [];

  awareness.getStates().forEach((state, clientId) => {
    const presence = readPresence(state);
    if (presence !== null) {
      peers.push({ ...presence, clientId, isLocal: clientId === local });
    }
  });

  return peers.sort((a, b) => a.clientId - b.clientId);
}
