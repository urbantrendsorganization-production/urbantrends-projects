/**
 * Rate limiter for outbound cursor updates.
 *
 * A pointer can fire far faster than the screen refreshes, and every awareness write is a
 * WebSocket frame fanned out to the whole room. This collapses any number of moves into at
 * most **one publish per animation frame**, sending only the most recent position — an
 * intermediate point that was never displayed is not worth a frame on the wire.
 */
import type { Point } from "./presence";

/** Injected so the batching can be tested against a fake clock. */
export interface Scheduler {
  request(callback: () => void): number;
  cancel(handle: number): void;
}

export interface CursorPublisher {
  /** Records the latest pointer position, or `null` when the pointer leaves the canvas. */
  move(point: Point | null): void;
  destroy(): void;
}

const rafScheduler: Scheduler = {
  request: (callback) => requestAnimationFrame(callback),
  cancel: (handle) => cancelAnimationFrame(handle),
};

export function createCursorPublisher(
  publish: (point: Point | null) => void,
  scheduler: Scheduler = rafScheduler,
): CursorPublisher {
  // 0 is never a valid handle, so it doubles as "nothing scheduled".
  let handle = 0;
  let pending: Point | null = null;
  let dirty = false;

  const flush = () => {
    handle = 0;
    if (!dirty) return;
    dirty = false;
    publish(pending);
  };

  return {
    move(point) {
      pending = point;
      dirty = true;
      if (handle === 0) handle = scheduler.request(flush);
    },

    destroy() {
      if (handle !== 0) scheduler.cancel(handle);
      handle = 0;
      dirty = false;
    },
  };
}
