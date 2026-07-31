"use client";

import { useCallback, useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import type { Awareness } from "y-protocols/awareness";

import { createCursorPublisher } from "./cursorPublisher";
import {
  createIdentity,
  readPeers,
  type Point,
  type PresenceUser,
  type RosterEntry,
} from "./presence";

export interface Presence {
  /** This tab's throwaway identity. */
  readonly self: PresenceUser;
  /** Who is connected. Changes only when membership does — not when a cursor moves. */
  readonly roster: readonly RosterEntry[];
  /** Publishes the local selection. Rate-unlimited: selection changes are user-paced. */
  select(ids: readonly string[]): void;
  /** Publishes the local pointer, batched to at most one update per animation frame. */
  moveCursor(point: Point | null): void;
}

const EMPTY: readonly RosterEntry[] = [];

/**
 * Identity only. Cursor and selection are excluded on purpose: they change constantly, and
 * a signature that included them would invalidate the roster sixty times a second.
 */
function rosterSignature(roster: readonly RosterEntry[]): string {
  return roster
    .map((entry) => `${entry.clientId}:${entry.user.name}:${entry.user.color}`)
    .join("|");
}

/**
 * Subscribes React to *membership*, and nothing else.
 *
 * Awareness fires `change` on every cursor movement in the room. Feeding that straight into
 * React would re-render the badges at frame rate, so the snapshot is cached behind an
 * identity-only signature: unless someone actually joined or left, `getSnapshot` returns the
 * previous array and React bails out without rendering.
 */
function useRoster(awareness: Awareness): readonly RosterEntry[] {
  const cache = useRef<{ signature: string; roster: readonly RosterEntry[] }>({
    signature: "",
    roster: EMPTY,
  });

  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      awareness.on("change", onStoreChange);
      return () => awareness.off("change", onStoreChange);
    },
    [awareness],
  );

  const getSnapshot = useCallback(() => {
    const roster: RosterEntry[] = readPeers(awareness).map((peer) => ({
      clientId: peer.clientId,
      user: peer.user,
      isLocal: peer.isLocal,
    }));

    const signature = rosterSignature(roster);
    if (signature !== cache.current.signature) {
      cache.current = { signature, roster };
    }
    return cache.current.roster;
  }, [awareness]);

  // The server renders no one: there is no connection yet, so the room is empty.
  return useSyncExternalStore(subscribe, getSnapshot, () => EMPTY);
}

/**
 * Publishes this tab's presence and exposes the room's membership.
 *
 * Everything written here goes to the awareness channel only. None of it touches the
 * `Y.Doc`, and none of it is persisted.
 */
export function usePresence(awareness: Awareness): Presence {
  // Seeded from the replica's client id, so reconnecting keeps the identity but switching
  // rooms (which builds a fresh doc, and with it a fresh client id) mints a new one.
  const self = useMemo(() => createIdentity(awareness.clientID), [awareness]);

  const publisher = useMemo(
    () =>
      createCursorPublisher((point) => {
        awareness.setLocalStateField("cursor", point);
      }),
    [awareness],
  );

  useEffect(() => {
    awareness.setLocalState({ user: self, cursor: null, selection: [] });

    return () => {
      publisher.destroy();
      // Withdraw presence explicitly so peers drop us immediately instead of waiting out
      // the staleness timeout.
      awareness.setLocalState(null);
    };
  }, [awareness, publisher, self]);

  const select = useCallback(
    (ids: readonly string[]) => {
      awareness.setLocalStateField("selection", [...ids]);
    },
    [awareness],
  );

  const moveCursor = useCallback(
    (point: Point | null) => publisher.move(point),
    [publisher],
  );

  return { self, roster: useRoster(awareness), select, moveCursor };
}
