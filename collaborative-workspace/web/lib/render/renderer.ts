/**
 * Canvas 2D renderer.
 *
 * Knows nothing about Yjs — it draws a `SceneState`, which the caller derives from the
 * document. Swapping in a different engine means reimplementing this file only.
 */
import type { Shape } from "@/lib/collab/shapes";

export interface SceneState {
  readonly shapes: readonly Shape[];
}

export interface Viewport {
  readonly width: number;
  readonly height: number;
}

/**
 * Matches the backing store to the element's CSS size and the device pixel ratio, so
 * rendering is crisp on HiDPI displays. Returns the viewport in CSS pixels — the same
 * coordinate space that pointer events and the document use.
 */
export function syncCanvasSize(canvas: HTMLCanvasElement): Viewport {
  const ratio = window.devicePixelRatio || 1;
  const { width, height } = canvas.getBoundingClientRect();

  const backingWidth = Math.round(width * ratio);
  const backingHeight = Math.round(height * ratio);
  if (canvas.width !== backingWidth || canvas.height !== backingHeight) {
    canvas.width = backingWidth;
    canvas.height = backingHeight;
  }

  return { width, height };
}

export function drawScene(
  ctx: CanvasRenderingContext2D,
  scene: SceneState,
  viewport: Viewport,
): void {
  const ratio = window.devicePixelRatio || 1;

  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, viewport.width, viewport.height);

  drawGrid(ctx, viewport);

  for (const shape of scene.shapes) {
    ctx.fillStyle = shape.fill;
    ctx.fillRect(shape.x, shape.y, shape.w, shape.h);

    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(0, 0, 0, 0.35)";
    ctx.strokeRect(shape.x + 0.5, shape.y + 0.5, shape.w - 1, shape.h - 1);
  }
}

const GRID_SPACING = 32;

function drawGrid(ctx: CanvasRenderingContext2D, viewport: Viewport): void {
  ctx.beginPath();
  for (let x = GRID_SPACING; x < viewport.width; x += GRID_SPACING) {
    ctx.moveTo(x + 0.5, 0);
    ctx.lineTo(x + 0.5, viewport.height);
  }
  for (let y = GRID_SPACING; y < viewport.height; y += GRID_SPACING) {
    ctx.moveTo(0, y + 0.5);
    ctx.lineTo(viewport.width, y + 0.5);
  }
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(127, 127, 127, 0.18)";
  ctx.stroke();
}
