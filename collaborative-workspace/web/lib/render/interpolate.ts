/**
 * Cursor smoothing.
 *
 * Peers publish at most one position per frame and the network delivers those in bursts, so
 * drawing raw positions makes remote cursors stutter. Each cursor is instead eased toward
 * its latest known position, which is what turns a sparse stream of points into a glide.
 *
 * This is display state, not shared state: it lives for the lifetime of a canvas and is
 * derived entirely from awareness.
 */
import type { Point } from "@/lib/collab/presence";

/**
 * Time to close ~63% of the remaining gap. Low enough that a cursor never feels like it is
 * lagging the peer who owns it, high enough to hide the gaps between updates.
 */
const TAU_MS = 70;

/** Below this the remaining distance is invisible, so the cursor is parked on its target. */
const SETTLED_PX = 0.05;

interface Position {
  x: number;
  y: number;
}

export class CursorTweens {
  private readonly positions = new Map<number, Position>();

  /**
   * Advances every cursor toward its target by `dtMs` and forgets any that disappeared.
   *
   * Returns `true` while at least one cursor is still in motion, which is the signal the
   * render loop uses to decide whether it needs another frame at all.
   */
  step(targets: ReadonlyMap<number, Point>, dtMs: number): boolean {
    for (const clientId of this.positions.keys()) {
      if (!targets.has(clientId)) this.positions.delete(clientId);
    }

    // Framerate-independent easing: the same fraction of the gap closes per unit of *time*,
    // so a 30fps tab and a 120Hz one animate at the same speed.
    const k = dtMs > 0 ? 1 - Math.exp(-dtMs / TAU_MS) : 0;
    let moving = false;

    for (const [clientId, target] of targets) {
      const current = this.positions.get(clientId);

      // First sighting — appear where the peer actually is. Easing in from a stale or
      // default position would fling a newly-arrived cursor across the canvas.
      if (current === undefined) {
        this.positions.set(clientId, { x: target.x, y: target.y });
        continue;
      }

      const dx = target.x - current.x;
      const dy = target.y - current.y;

      if (Math.abs(dx) < SETTLED_PX && Math.abs(dy) < SETTLED_PX) {
        current.x = target.x;
        current.y = target.y;
        continue;
      }

      current.x += dx * k;
      current.y += dy * k;
      moving = true;
    }

    return moving;
  }

  positionOf(clientId: number): Point | null {
    return this.positions.get(clientId) ?? null;
  }
}
