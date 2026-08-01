/**
 * The shared document shape. This mirrors what `server/src/sync/` relays and must change
 * on both sides in the same PR.
 *
 * Layout: `Y.Map` named `shapes`, keyed by object id, each value a nested `Y.Map` with
 * per-property keys. The nesting is deliberate — it is what lets the CRDT resolve
 * concurrent edits on its own:
 *
 *   - two users dragging different shapes never touch the same key
 *   - one user moving a shape while another recolors it: both edits survive
 *
 * Storing a plain JSON object as the map value would instead make every write a
 * whole-object replace, and the last writer would silently clobber the other.
 */
import * as Y from "yjs";

const SHAPES_KEY = "shapes";

/** A rectangle, as read out of the CRDT. Plain data — safe to hand to the renderer. */
export interface Shape {
  readonly id: string;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
  readonly fill: string;
}

/** Per-shape node: per-property keys, never a replaced blob. */
type YShape = Y.Map<number | string>;

function shapesMap(doc: Y.Doc): Y.Map<YShape> {
  return doc.getMap<YShape>(SHAPES_KEY);
}

function readNumber(node: YShape, key: string): number | null {
  const value = node.get(key);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Projects one CRDT node into a `Shape`, or `null` if it is not (yet) a complete
 * rectangle. A concurrent peer can legitimately have a half-written node in flight, so a
 * missing key is a normal state to skip, not an error.
 */
function readShape(id: string, node: YShape): Shape | null {
  const x = readNumber(node, "x");
  const y = readNumber(node, "y");
  const w = readNumber(node, "w");
  const h = readNumber(node, "h");
  const fill = node.get("fill");

  if (x === null || y === null || w === null || h === null) return null;
  if (typeof fill !== "string") return null;

  return { id, x, y, w, h, fill };
}

/**
 * Reads the whole scene out of the document. Called at paint time — the result is a
 * derived projection, never stored.
 *
 * Sorted by id because `Y.Map` iteration order is not guaranteed to match across
 * replicas, and two tabs must paint overlapping rectangles in the same order. (A real
 * z-index belongs in the model once layering is a feature.)
 */
export function readScene(doc: Y.Doc): Shape[] {
  const shapes: Shape[] = [];
  shapesMap(doc).forEach((node, id) => {
    const shape = readShape(id, node);
    if (shape !== null) shapes.push(shape);
  });
  return shapes.sort((a, b) => a.id.localeCompare(b.id));
}

/** Inserts a rectangle. One transaction, so peers see it appear atomically. */
export function createShape(doc: Y.Doc, shape: Shape): void {
  doc.transact(() => {
    shapesMap(doc).set(
      shape.id,
      new Y.Map<number | string>([
        ["x", shape.x],
        ["y", shape.y],
        ["w", shape.w],
        ["h", shape.h],
        ["fill", shape.fill],
      ]),
    );
  });
}

/**
 * Moves a rectangle by writing `x`/`y` on its node. Only those two keys are touched, so a
 * concurrent edit to any other property is untouched.
 */
export function moveShape(doc: Y.Doc, id: string, x: number, y: number): void {
  const node = shapesMap(doc).get(id);
  // Concurrently deleted by another peer. The CRDT already settled that; nothing to do.
  if (node === undefined) return;

  doc.transact(() => {
    node.set("x", x);
    node.set("y", y);
  });
}

/** Topmost shape containing the point, or `null`. Reverse paint order = topmost first. */
export function hitTest(
  shapes: readonly Shape[],
  x: number,
  y: number,
): Shape | null {
  for (let i = shapes.length - 1; i >= 0; i -= 1) {
    const shape = shapes[i];
    if (
      x >= shape.x &&
      x <= shape.x + shape.w &&
      y >= shape.y &&
      y <= shape.y + shape.h
    ) {
      return shape;
    }
  }
  return null;
}
