"use client";

import { useEffect, useMemo, useState } from "react";
import { Awareness } from "y-protocols/awareness";
import * as Y from "yjs";

import { openConnection } from "./provider";

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export interface Collab {
  /**
   * The document. This is the single source of truth for the room — shape data is read
   * out of it at paint time and is never mirrored into React state.
   */
  readonly doc: Y.Doc;
  /**
   * The presence channel. Strictly separate from `doc`: it is relayed but never merged
   * into the document and never persisted.
   */
  readonly awareness: Awareness;
  readonly status: ConnectionStatus;
}

function toStatus(value: string): ConnectionStatus {
  return value === "connected" || value === "connecting"
    ? value
    : "disconnected";
}

/**
 * Opens a document for `room` and keeps it connected for the component's lifetime.
 *
 * The doc deliberately survives disconnects: local edits keep applying while offline and
 * merge on reconnect, so only the transport is torn down, never the replica.
 */
export function useCollab(room: string): Collab {
  // A Y.Doc is plain in-memory state with no DOM dependency, so it is safe to build
  // during render (including on the server, where it simply goes unused). Naming it after
  // the room both identifies the replica and makes a room change yield a fresh document.
  const doc = useMemo(() => new Y.Doc({ guid: room }), [room]);
  // Also plain in-memory state. Building it alongside the doc rather than letting the
  // provider create it keeps presence available to render from before the socket opens,
  // and ties its lifetime to the replica instead of to the transport.
  const awareness = useMemo(() => new Awareness(doc), [doc]);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");

  useEffect(() => {
    const connection = openConnection(room, doc, awareness);

    // setState from a subscription callback, not from the effect body — this is the
    // external system telling React that something changed.
    const onStatus = (event: { status: string }) => setStatus(toStatus(event.status));
    connection.provider.on("status", onStatus);

    return () => {
      connection.provider.off("status", onStatus);
      connection.destroy();
      // The provider only detaches its listeners from an awareness it did not create, so
      // tearing down the instance (and its staleness timer) is ours to do.
      awareness.destroy();
    };
  }, [awareness, doc, room]);

  return { doc, awareness, status };
}
