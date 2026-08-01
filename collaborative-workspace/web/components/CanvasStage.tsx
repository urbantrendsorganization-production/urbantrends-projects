"use client";

import { useCallback, useEffect, useRef } from "react";

import { readPeers } from "@/lib/collab/presence";
import { createShape, hitTest, moveShape, readScene } from "@/lib/collab/shapes";
import { useCollab } from "@/lib/collab/useCollab";
import { usePresence } from "@/lib/collab/usePresence";
import { CursorTweens } from "@/lib/render/interpolate";
import { drawPresence, type PresencePeer } from "@/lib/render/presenceLayer";
import { drawScene, syncCanvasSize } from "@/lib/render/renderer";
import { PresenceBadges } from "./PresenceBadges";

import styles from "./CanvasStage.module.css";

const PALETTE = [
  "#ef476f",
  "#ffd166",
  "#06d6a0",
  "#118ab2",
  "#8338ec",
  "#fb5607",
] as const;

/** Which shape the pointer is dragging, and where inside it the pointer grabbed. */
interface Drag {
  readonly id: string;
  readonly offsetX: number;
  readonly offsetY: number;
}

function pick<T>(values: readonly T[]): T {
  return values[Math.floor(Math.random() * values.length)];
}

export function CanvasStage({ room }: { room: string }) {
  const { doc, awareness, status } = useCollab(room);
  const { roster, select, moveCursor } = usePresence(awareness);

  const sceneRef = useRef<HTMLCanvasElement>(null);
  const presenceRef = useRef<HTMLCanvasElement>(null);

  // Refs, not state: pointer interaction and selection are per-user UI concerns. Neither
  // belongs in the document, and neither should trigger a React render.
  const dragRef = useRef<Drag | null>(null);
  const selectionRef = useRef<readonly string[]>([]);

  // ---- Scene layer -------------------------------------------------------------------
  // Unchanged from Phase 1: every repaint reads the scene straight out of the CRDT, so
  // there is no copy of shape data anywhere in React. Event-driven — this layer has no
  // reason to repaint because a cursor moved.
  useEffect(() => {
    const canvas = sceneRef.current;
    if (canvas === null) return;

    const ctx = canvas.getContext("2d");
    if (ctx === null) return;

    let frame = 0;
    const paint = () => {
      frame = 0;
      const viewport = syncCanvasSize(canvas);
      drawScene(ctx, { shapes: readScene(doc) }, viewport);
    };
    const schedule = () => {
      if (frame === 0) frame = requestAnimationFrame(paint);
    };

    schedule();
    doc.on("update", schedule);

    const resizeObserver = new ResizeObserver(schedule);
    resizeObserver.observe(canvas);

    return () => {
      doc.off("update", schedule);
      resizeObserver.disconnect();
      if (frame !== 0) cancelAnimationFrame(frame);
    };
  }, [doc]);

  // ---- Presence layer ----------------------------------------------------------------
  // Its own canvas and its own loop. Interpolated cursors have to animate between document
  // updates, so unlike the scene this layer runs a continuous rAF — but only while a cursor
  // is actually in flight. Once every tween has settled the loop stops, and an idle room
  // costs no frames at all.
  //
  // It also subscribes to `doc.update`, because selection outlines are drawn around shape
  // geometry: when a peer drags a rectangle you have selected, the outline has to follow it.
  useEffect(() => {
    const canvas = presenceRef.current;
    if (canvas === null) return;

    const ctx = canvas.getContext("2d");
    if (ctx === null) return;

    const tweens = new CursorTweens();
    let frame = 0;
    let last = 0;

    const paint = (now: number) => {
      frame = 0;
      const elapsed = last === 0 ? 0 : now - last;
      last = now;

      const peers = readPeers(awareness);
      const targets = new Map<number, { x: number; y: number }>();
      for (const peer of peers) {
        // Our own cursor is never drawn — the OS pointer is already there — so tweening it
        // would only keep the loop awake for something invisible.
        if (peer.isLocal || peer.cursor === null) continue;
        targets.set(peer.clientId, peer.cursor);
      }

      const moving = tweens.step(targets, elapsed);

      const rendered: PresencePeer[] = peers.map((peer) => ({
        clientId: peer.clientId,
        name: peer.user.name,
        color: peer.user.color,
        cursor: tweens.positionOf(peer.clientId),
        selection: peer.selection,
        isLocal: peer.isLocal,
      }));

      const viewport = syncCanvasSize(canvas);
      drawPresence(ctx, rendered, readScene(doc), viewport);

      if (moving) {
        frame = requestAnimationFrame(paint);
      } else {
        // Idle. Reset the clock so the next wake-up does not ease by however long the loop
        // was asleep.
        last = 0;
      }
    };

    const schedule = () => {
      if (frame === 0) frame = requestAnimationFrame(paint);
    };

    schedule();
    awareness.on("change", schedule);
    doc.on("update", schedule);

    const resizeObserver = new ResizeObserver(schedule);
    resizeObserver.observe(canvas);

    return () => {
      awareness.off("change", schedule);
      doc.off("update", schedule);
      resizeObserver.disconnect();
      if (frame !== 0) cancelAnimationFrame(frame);
    };
  }, [awareness, doc]);

  // ---- Interaction -------------------------------------------------------------------

  /** Records the selection locally and mirrors it into awareness. Never into the doc. */
  const applySelection = useCallback(
    (ids: readonly string[]) => {
      selectionRef.current = ids;
      select(ids);
    },
    [select],
  );

  const pointAt = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const { x, y } = pointAt(event);
    const hit = hitTest(readScene(doc), x, y);

    if (hit === null) {
      applySelection([]);
      return;
    }

    const current = selectionRef.current;
    if (event.shiftKey) {
      applySelection(
        current.includes(hit.id)
          ? current.filter((id) => id !== hit.id)
          : [...current, hit.id],
      );
    } else if (!current.includes(hit.id)) {
      // Clicking inside an existing multi-selection keeps it, so it can be dragged.
      applySelection([hit.id]);
    }

    dragRef.current = { id: hit.id, offsetX: x - hit.x, offsetY: y - hit.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const point = pointAt(event);

    // Batched to one publish per animation frame no matter how fast the pointer fires.
    moveCursor(point);

    const drag = dragRef.current;
    if (drag === null) return;

    // Writes go to the document; the repaint happens because the doc emitted an update,
    // not because we moved anything locally. The local dragger takes exactly the same
    // path as a remote peer.
    moveShape(doc, drag.id, point.x - drag.offsetX, point.y - drag.offsetY);
  };

  const onPointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (dragRef.current === null) return;
    dragRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  // An absent cursor, so peers stop drawing one rather than leaving it frozen at the edge.
  const onPointerLeave = () => moveCursor(null);

  const addRectangle = useCallback(() => {
    const canvas = sceneRef.current;
    if (canvas === null) return;

    const { width, height } = canvas.getBoundingClientRect();
    const w = 120;
    const h = 80;

    createShape(doc, {
      id: crypto.randomUUID(),
      x: Math.round(Math.random() * Math.max(0, width - w)),
      y: Math.round(Math.random() * Math.max(0, height - h)),
      w,
      h,
      fill: pick(PALETTE),
    });
  }, [doc]);

  return (
    <div className={styles.stage}>
      <header className={styles.bar}>
        <div className={styles.room}>
          room <strong>{room}</strong>
        </div>
        <button type="button" onClick={addRectangle} className={styles.button}>
          Add rectangle
        </button>
        <PresenceBadges roster={roster} />
        <span className={styles.status} data-status={status}>
          {status}
        </span>
      </header>

      {/* Two layers: the scene repaints on document updates, presence animates on its own
          loop. The overlay never takes pointer events, so input still lands on the scene. */}
      <div className={styles.layers}>
        <canvas
          ref={sceneRef}
          className={styles.canvas}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onPointerLeave={onPointerLeave}
        />
        <canvas ref={presenceRef} className={`${styles.canvas} ${styles.overlay}`} />
      </div>
    </div>
  );
}
