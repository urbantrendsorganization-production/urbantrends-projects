/**
 * The presence overlay: remote cursors and everyone's selection outlines.
 *
 * Deliberately a separate layer from `renderer.ts`. The scene repaints only when the
 * document changes; presence has to animate between those changes, and there is no reason
 * to re-rasterise every rectangle because a cursor moved a pixel.
 *
 * Like the scene renderer this knows nothing about Yjs — it draws what it is handed.
 */
import type { Point } from "@/lib/collab/presence";
import type { Shape } from "@/lib/collab/shapes";
import type { Viewport } from "./renderer";

export interface PresencePeer {
  readonly clientId: number;
  readonly name: string;
  readonly color: string;
  /** Interpolated position, or `null` if the peer's pointer is off-canvas. */
  readonly cursor: Point | null;
  readonly selection: readonly string[];
  readonly isLocal: boolean;
}

const OUTLINE_WIDTH = 2;
const OUTLINE_GAP = 3;

const CURSOR_HEIGHT = 18;
const LABEL_FONT = "500 12px system-ui, sans-serif";
const LABEL_PADDING_X = 7;
const LABEL_HEIGHT = 20;
const LABEL_RADIUS = 6;
const LABEL_OFFSET_X = 12;
const LABEL_OFFSET_Y = 14;

export function drawPresence(
  ctx: CanvasRenderingContext2D,
  peers: readonly PresencePeer[],
  shapes: readonly Shape[],
  viewport: Viewport,
): void {
  const ratio = window.devicePixelRatio || 1;

  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, viewport.width, viewport.height);

  // Outlines first so a cursor is never hidden behind one.
  drawSelections(ctx, peers, shapes);

  for (const peer of peers) {
    // Our own cursor is already on screen — the operating system draws it.
    if (peer.isLocal || peer.cursor === null) continue;
    drawCursor(ctx, peer.cursor, peer.color, peer.name, viewport);
  }
}

function drawSelections(
  ctx: CanvasRenderingContext2D,
  peers: readonly PresencePeer[],
  shapes: readonly Shape[],
): void {
  const byId = new Map(shapes.map((shape) => [shape.id, shape]));
  // Two people selecting the same rectangle each get their own ring rather than one
  // silently painting over the other.
  const rings = new Map<string, number>();

  for (const peer of peers) {
    for (const id of peer.selection) {
      const shape = byId.get(id);
      if (shape === undefined) continue;

      const ring = rings.get(id) ?? 0;
      rings.set(id, ring + 1);

      const inset = OUTLINE_GAP + ring * (OUTLINE_WIDTH + 1);
      ctx.lineWidth = OUTLINE_WIDTH;
      ctx.strokeStyle = peer.color;
      ctx.strokeRect(
        shape.x - inset,
        shape.y - inset,
        shape.w + inset * 2,
        shape.h + inset * 2,
      );
    }
  }
}

function drawCursor(
  ctx: CanvasRenderingContext2D,
  at: Point,
  color: string,
  name: string,
  viewport: Viewport,
): void {
  ctx.save();
  ctx.translate(at.x, at.y);

  // A classic pointer arrow, drawn from its tip so the hotspot sits exactly on the
  // published coordinate.
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(0, CURSOR_HEIGHT);
  ctx.lineTo(4.6, 13.7);
  ctx.lineTo(7.5, 19.4);
  ctx.lineTo(10.6, 17.9);
  ctx.lineTo(7.7, 12.3);
  ctx.lineTo(13.2, 11.7);
  ctx.closePath();

  ctx.fillStyle = color;
  ctx.fill();
  // A light rim keeps the arrow readable when it crosses a rectangle of a similar colour.
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "rgba(255, 255, 255, 0.9)";
  ctx.lineJoin = "round";
  ctx.stroke();

  ctx.restore();

  drawLabel(ctx, at, color, name, viewport);
}

function drawLabel(
  ctx: CanvasRenderingContext2D,
  at: Point,
  color: string,
  name: string,
  viewport: Viewport,
): void {
  ctx.font = LABEL_FONT;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";

  const width = ctx.measureText(name).width + LABEL_PADDING_X * 2;

  // Flip the label to the other side rather than letting it run off the canvas.
  const x =
    at.x + LABEL_OFFSET_X + width > viewport.width
      ? at.x - LABEL_OFFSET_X - width
      : at.x + LABEL_OFFSET_X;
  const y =
    at.y + LABEL_OFFSET_Y + LABEL_HEIGHT > viewport.height
      ? at.y - LABEL_OFFSET_Y - LABEL_HEIGHT
      : at.y + LABEL_OFFSET_Y;

  ctx.beginPath();
  ctx.roundRect(x, y, width, LABEL_HEIGHT, LABEL_RADIUS);
  ctx.fillStyle = color;
  ctx.fill();

  ctx.fillStyle = "#ffffff";
  ctx.fillText(name, x + LABEL_PADDING_X, y + LABEL_HEIGHT / 2);
}
