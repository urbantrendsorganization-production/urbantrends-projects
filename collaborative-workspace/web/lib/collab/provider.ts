/**
 * The connection to the Axum relay.
 *
 * `y-websocket` speaks the same y-sync protocol the server implements via `yrs::sync`, and
 * already handles reconnect + resync, so there is no custom provider here.
 */
import type * as Y from "yjs";
import type { Awareness } from "y-protocols/awareness";
import { WebsocketProvider } from "y-websocket";

const DEFAULT_WS_URL = "ws://localhost:4000/ws";

/** `y-websocket` builds its URL as `${base}/${room}`, so the room is the WS path segment. */
function baseUrl(): string {
  return process.env.NEXT_PUBLIC_WS_URL ?? DEFAULT_WS_URL;
}

export interface Connection {
  readonly provider: WebsocketProvider;
  destroy(): void;
}

/**
 * Connects `doc` to `room`. Browser only — call from an effect, never during render.
 *
 * `awareness` is supplied rather than left to the provider so presence has the same
 * lifetime as the document and is available to render from before the socket opens.
 */
export function openConnection(
  room: string,
  doc: Y.Doc,
  awareness: Awareness,
): Connection {
  const provider = new WebsocketProvider(baseUrl(), room, doc, {
    awareness,
    // Off on purpose. y-websocket also syncs same-origin tabs over a BroadcastChannel,
    // which would make two tabs converge without the server ever being involved — the
    // relay could be entirely broken and the demo would still look like it worked.
    disableBc: true,
  });

  return {
    provider,
    destroy() {
      provider.destroy();
    },
  };
}
