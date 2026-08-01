import assert from "node:assert/strict";
import { test } from "node:test";

import type { Point } from "../collab/presence.ts";
import { CursorTweens } from "./interpolate.ts";

const FRAME_MS = 16;

function targets(entries: [number, Point][]): Map<number, Point> {
  return new Map(entries);
}

test("a cursor's first sighting snaps instead of flying in", () => {
  const tweens = new CursorTweens();

  const moving = tweens.step(targets([[1, { x: 400, y: 300 }]]), FRAME_MS);

  assert.deepEqual(tweens.positionOf(1), { x: 400, y: 300 });
  assert.equal(moving, false, "an already-correct cursor needs no further frames");
});

test("a moved cursor glides rather than snapping", () => {
  const tweens = new CursorTweens();
  tweens.step(targets([[1, { x: 0, y: 0 }]]), FRAME_MS);

  const moving = tweens.step(targets([[1, { x: 100, y: 0 }]]), FRAME_MS);
  const after = tweens.positionOf(1);
  assert.ok(after !== null);

  assert.equal(moving, true, "the loop keeps running while a cursor is in flight");
  assert.ok(after.x > 0, "it left the old position");
  assert.ok(after.x < 100, "but did not jump to the new one");
});

test("a cursor converges on its target and then settles", () => {
  const tweens = new CursorTweens();
  tweens.step(targets([[1, { x: 0, y: 0 }]]), FRAME_MS);

  const destination = targets([[1, { x: 100, y: 50 }]]);
  let frames = 0;
  while (tweens.step(destination, FRAME_MS)) {
    frames += 1;
    assert.ok(frames < 240, "a tween must not animate forever");
  }

  assert.deepEqual(tweens.positionOf(1), { x: 100, y: 50 });
  // ~70ms time constant: visually immediate, but spread over enough frames to be a glide.
  assert.ok(frames > 4, `expected a smooth ramp, settled in ${frames} frames`);
});

test("easing is framerate-independent", () => {
  const destination = targets([[1, { x: 100, y: 0 }]]);

  const fast = new CursorTweens();
  fast.step(targets([[1, { x: 0, y: 0 }]]), 8);
  for (let i = 0; i < 8; i += 1) fast.step(destination, 8);

  const slow = new CursorTweens();
  slow.step(targets([[1, { x: 0, y: 0 }]]), 32);
  for (let i = 0; i < 2; i += 1) slow.step(destination, 32);

  const a = fast.positionOf(1);
  const b = slow.positionOf(1);
  assert.ok(a !== null && b !== null);
  // Same elapsed time (64ms) at 125fps and at 31fps must land in the same place.
  assert.ok(
    Math.abs(a.x - b.x) < 0.5,
    `120Hz reached ${a.x.toFixed(2)}, 30Hz reached ${b.x.toFixed(2)}`,
  );
});

test("a departed peer's cursor is forgotten", () => {
  const tweens = new CursorTweens();
  tweens.step(targets([[1, { x: 10, y: 10 }]]), FRAME_MS);
  assert.notEqual(tweens.positionOf(1), null);

  tweens.step(targets([]), FRAME_MS);
  assert.equal(tweens.positionOf(1), null, "presence is ephemeral, and so is its tween");
});
