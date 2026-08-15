/**
 * A node description and an action description. About sixty lines, on purpose.
 *
 * The widget renders into a host page it does not control, so it ships its own
 * renderer rather than React's. That could have been a component library; it is
 * this instead, for two reasons.
 *
 * **Weight.** React and react-dom are roughly 45 kB gzipped before a single
 * screen exists. The client this widget serves is on 3G, arriving cold from a
 * WhatsApp link, and the design's success measure is link-to-paid-deposit in
 * under sixty seconds. Forty-five kilobytes of framework to draw eight screens
 * of buttons is most of that budget spent on machinery none of these screens
 * needs — there is no list virtualisation here, no animation system, no
 * concurrent anything.
 *
 * **The host's copy.** A host page may already run React, at a different
 * version, and putting a second one on the page is somewhere between wasteful
 * and a hazard depending on how the host loads it. Owning nothing global is the
 * only version of this that is safe everywhere.
 *
 * ## Why events are data instead of closures
 *
 * A `VNode` carries `on: { click: { type: "chooseSlot", startsAt } }` rather
 * than a function. A closure would be simpler to write and would work. This is
 * better here for one specific reason: it keeps `view.ts` returning **pure
 * data**, so the tests can assert what a control does — that Continue
 * dispatches `confirm`, that the disabled one dispatches nothing — with no
 * DOM, no flow, and no stub. Every decision in the flow is already tested in
 * `booking-core`; what is left to test here is the wiring, and wiring you can
 * read as data is wiring you can assert.
 *
 * The cost is one small enumeration: `mount.ts` has a switch that turns an
 * `Action` into a call on the flow. It is the only place in the widget that
 * knows both halves, and it is twenty lines.
 */

/** Attribute values. `false` and `undefined` mean "do not set the attribute". */
export type AttrValue = string | number | boolean | undefined;

/**
 * What a control does, as a value.
 *
 * Deliberately serialisable — no slot objects, no service objects, only the
 * identifiers needed to find them again. `mount.ts` resolves `startsAt` back to
 * a slot through `offeredSlots(state)`, which is the same selector the view
 * drew the grid from, so the two cannot disagree about which slot is which.
 */
export type Action =
  | { type: "back" }
  | { type: "chooseService"; id: string }
  | { type: "chooseStaff"; id: string }
  | { type: "chooseDate"; date: string }
  | { type: "chooseSlot"; startsAt: string }
  /** The value is read off the input at dispatch time; carrying it here would
   *  mean re-rendering the tree on every keystroke to keep it current. */
  | { type: "setPhone" }
  | { type: "confirm" }
  | { type: "release" }
  | { type: "resend" }
  | { type: "pickAnotherTime" };

export interface VNode {
  tag: string;
  attrs: Record<string, AttrValue>;
  /** DOM event name to the action it dispatches. */
  on: Partial<Record<"click" | "input", Action>>;
  children: Child[];
  /** Identity across renders, so the patcher reuses a node instead of
   *  replacing it. The phone input is why this exists: replacing a focused
   *  input mid-booking drops the keyboard on a phone. */
  key?: string;
}

export type Child = VNode | string | null | false;

export function h(
  tag: string,
  attrs: Record<string, AttrValue> = {},
  children: Child[] = [],
): VNode {
  const { key, ...rest } = attrs;
  return {
    tag,
    attrs: rest,
    on: {},
    children: children.filter((child) => child !== null && child !== false && child !== ""),
    key: typeof key === "string" ? key : undefined,
  };
}

/** `h(...)` with an action bound. Separate so the common node stays a one-liner. */
export function on(node: VNode, event: "click" | "input", action: Action): VNode {
  node.on[event] = action;
  return node;
}

/** Every action a tree dispatches, in document order. For the tests. */
export function actionsIn(node: Child): Action[] {
  if (!node || typeof node === "string") return [];
  const mine = Object.values(node.on).filter(Boolean) as Action[];
  return [...mine, ...node.children.flatMap(actionsIn)];
}

/** The tree's visible text, joined. For the tests: what the client can read. */
export function textIn(node: Child): string {
  if (!node) return "";
  if (typeof node === "string") return node;
  return node.children.map(textIn).join("");
}

/** Depth-first walk, so a test can ask a question about every node. */
export function everyNode(node: Child): VNode[] {
  if (!node || typeof node === "string") return [];
  return [node, ...node.children.flatMap(everyNode)];
}
