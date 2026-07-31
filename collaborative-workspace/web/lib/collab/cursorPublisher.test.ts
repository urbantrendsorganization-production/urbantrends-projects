import assert from "node:assert/strict";
import { test } from "node:test";

import { createCursorPublisher, type Scheduler } from "./cursorPublisher.ts";
import type { Point } from "./presence.ts";

/** Stands in for requestAnimationFrame so frames can be stepped deterministically. */
function fakeFrames() {
  let next = 1;
  const queued = new Map<number, () => void>();

  const scheduler: Scheduler = {
    request(callback) {
      const handle = next++;
      queued.set(handle, callback);
      return handle;
    },
    cancel(handle) {
      queued.delete(handle);
    },
  };

  return {
    scheduler,
    pending: () => queued.size,
    /** Runs everything queued for this frame. */
    tick() {
      const due = [...queued.values()];
      queued.clear();
      for (const callback of due) callback();
    },
  };
}

function recorder() {
  const published: (Point | null)[] = [];
  return { published, publish: (point: Point | null) => void published.push(point) };
}

test("a burst of moves costs exactly one publish per frame", () => {
  const frames = fakeFrames();
  const { published, publish } = recorder();
  const publisher = createCursorPublisher(publish, frames.scheduler);

  for (let i = 0; i < 500; i += 1) {
    publisher.move({ x: i, y: i });
  }
  assert.equal(published.length, 0, "nothing is sent before the frame runs");

  frames.tick();
  assert.equal(published.length, 1, "500 moves collapse into a single publish");
  assert.deepEqual(
    published[0],
    { x: 499, y: 499 },
    "the newest position wins; skipped points were never displayed",
  );
});

test("a sustained drag never exceeds one publish per frame", () => {
  const frames = fakeFrames();
  const { published, publish } = recorder();
  const publisher = createCursorPublisher(publish, frames.scheduler);

  for (let frame = 0; frame < 60; frame += 1) {
    // A pointer can comfortably out-run the display; the publisher must not.
    for (let i = 0; i < 8; i += 1) publisher.move({ x: frame * 8 + i, y: 0 });
    frames.tick();
  }

  assert.equal(published.length, 60, "one publish per frame across the whole drag");
});

test("an idle pointer schedules no frames at all", () => {
  const frames = fakeFrames();
  const { published, publish } = recorder();
  const publisher = createCursorPublisher(publish, frames.scheduler);

  publisher.move({ x: 1, y: 1 });
  frames.tick();
  assert.equal(published.length, 1);

  // No movement since the flush, so the loop must not keep itself alive.
  assert.equal(frames.pending(), 0);
  frames.tick();
  assert.equal(published.length, 1, "an idle pointer publishes nothing");
});

test("leaving the canvas publishes an absent cursor", () => {
  const frames = fakeFrames();
  const { published, publish } = recorder();
  const publisher = createCursorPublisher(publish, frames.scheduler);

  publisher.move({ x: 5, y: 5 });
  frames.tick();
  publisher.move(null);
  frames.tick();

  assert.deepEqual(published, [{ x: 5, y: 5 }, null]);
});

test("destroy drops the pending frame", () => {
  const frames = fakeFrames();
  const { published, publish } = recorder();
  const publisher = createCursorPublisher(publish, frames.scheduler);

  publisher.move({ x: 1, y: 1 });
  publisher.destroy();
  frames.tick();

  assert.equal(published.length, 0, "a torn-down publisher must not write to awareness");
});
