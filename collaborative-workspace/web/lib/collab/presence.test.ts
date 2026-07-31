import assert from "node:assert/strict";
import { test } from "node:test";

import { createIdentity, initials, readPresence } from "./presence.ts";

test("identity is deterministic in the client id", () => {
  const a = createIdentity(1842771848);
  const b = createIdentity(1842771848);

  assert.deepEqual(a, b, "the same replica must not change name or colour mid-session");
  assert.match(a.color, /^#[0-9a-f]{6}$/);
  assert.match(a.name, /^\w+ \w+$/);
});

test("different clients get different identities", () => {
  const names = new Set<string>();
  const colors = new Set<string>();
  for (let clientId = 1; clientId <= 64; clientId += 1) {
    const identity = createIdentity(clientId * 7919);
    names.add(identity.name);
    colors.add(identity.color);
  }

  assert.ok(names.size > 50, `expected well-spread names, got ${names.size}/64`);
  assert.ok(colors.size >= 8, `expected the whole palette in use, got ${colors.size}`);
});

test("initials read from the first and last word", () => {
  assert.equal(initials("Swift Heron"), "SH");
  assert.equal(initials("Ada"), "AD");
  assert.equal(initials("  "), "?");
});

test("a well-formed presence payload round-trips", () => {
  const state = readPresence({
    user: { id: "7", name: "Swift Heron", color: "#0090ff" },
    cursor: { x: 12.5, y: 40 },
    selection: ["rect-1", "rect-2"],
  });

  assert.deepEqual(state, {
    user: { id: "7", name: "Swift Heron", color: "#0090ff" },
    cursor: { x: 12.5, y: 40 },
    selection: ["rect-1", "rect-2"],
  });
});

test("presence from an untrusted peer is validated, not cast", () => {
  // Awareness payloads are arbitrary JSON written by other clients.
  assert.equal(readPresence(null), null);
  assert.equal(readPresence("nope"), null);
  assert.equal(readPresence({}), null, "no identity, no peer");
  assert.equal(
    readPresence({ user: { id: "1", name: "X", color: "javascript:alert(1)" } }),
    null,
    "a colour goes straight into fillStyle, so only the exact literal shape is accepted",
  );

  const partial = readPresence({
    user: { id: "1", name: "X", color: "#ffffff" },
    cursor: { x: "over there", y: 3 },
    selection: ["ok", 42, null],
  });
  assert.equal(partial?.cursor, null, "a malformed cursor is an absent one");
  assert.deepEqual(partial?.selection, ["ok"], "non-string ids are dropped");
});

test("a hostile selection cannot make us paint an unbounded list", () => {
  const state = readPresence({
    user: { id: "1", name: "X", color: "#ffffff" },
    cursor: null,
    selection: Array.from({ length: 10_000 }, (_, i) => `id-${i}`),
  });

  assert.equal(state?.selection.length, 512);
});
