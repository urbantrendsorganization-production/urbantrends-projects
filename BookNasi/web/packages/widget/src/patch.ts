/**
 * The reconciler. Fifty lines, and the only part of the renderer with a bug in
 * it worth testing.
 *
 * ## Why not re-create the tree on every render
 *
 * Because the countdown ticks once a second for three minutes, and a full
 * rebuild each tick would (a) restart the progress bar's CSS transition, so the
 * one animation that must be linear and honest would stutter, (b) throw away
 * and rebuild ~200 nodes a second on the low-end Android this product is aimed
 * at, and (c) — the one that actually costs money — destroy the phone input
 * while the client is typing into it, which on a phone means the keyboard
 * closes. That happens on the confirm screen, one control away from the
 * deposit.
 *
 * ## Why it takes a document instead of using one
 *
 * So it can be tested. `mount.ts` is allowed to touch the browser and is
 * therefore the file no test can reach; everything that can be moved out of it
 * has been, and this is the largest piece. The tests pass a fake document of
 * about eighty lines and assert the things that actually go wrong in a
 * hand-written patcher: an attribute that should have been removed and was not,
 * a keyed node that was rebuilt instead of reused, a stale text node.
 *
 * `check-widget.mjs` enforces the boundary — a `document` in this file fails
 * the build, exactly as `check-no-framework.mjs` does for `booking-core`.
 */

import type { Child, VNode } from "./vdom";

/* The narrowest shape of the DOM this file needs. Real `Element` and
   `Document` satisfy these structurally, so nothing is cast at the call site. */

export interface NodeLike {
  nodeType: number;
}

export interface TextLike extends NodeLike {
  nodeValue: string | null;
}

export interface ElLike extends NodeLike {
  readonly tagName: string;
  readonly childNodes: ArrayLike<NodeLike>;
  readonly attributes: ArrayLike<{ name: string }>;
  getAttribute(name: string): string | null;
  setAttribute(name: string, value: string): void;
  removeAttribute(name: string): void;
  appendChild(child: NodeLike): unknown;
  removeChild(child: NodeLike): unknown;
  replaceChild(next: NodeLike, prev: NodeLike): unknown;
}

export interface DocLike {
  createElement(tag: string): ElLike;
  createTextNode(text: string): TextLike;
}

export interface PatchOptions {
  doc: DocLike;
  /** Records what an element dispatches. Called on create and on every update,
   *  because the action can change while the element does not — the same slot
   *  button on a different day. */
  bind(el: ElLike, on: VNode["on"]): void;
  /** True while the client is typing into this element. Its `value` is then
   *  left alone: the state already came from it, and writing it back moves the
   *  caret to the end mid-number. */
  isFocused(el: ElLike): boolean;
}

const ELEMENT = 1;
const TEXT = 3;

/** Where a `key` is stamped. An attribute rather than a side table so that a
 *  reused node can be recognised after any amount of DOM meddling, and so the
 *  reuse is visible in devtools when it goes wrong. */
const KEY_ATTR = "data-bn-key";

export function patchChildren(opts: PatchOptions, parent: ElLike, children: Child[]): void {
  const wanted = children.filter((child): child is VNode | string => Boolean(child));

  for (let index = 0; index < wanted.length; index += 1) {
    const vnode = wanted[index];
    const existing = parent.childNodes[index] as NodeLike | undefined;

    if (typeof vnode === "string") {
      if (existing && existing.nodeType === TEXT) {
        const text = existing as TextLike;
        if (text.nodeValue !== vnode) text.nodeValue = vnode;
      } else {
        const text = opts.doc.createTextNode(vnode);
        if (existing) parent.replaceChild(text, existing);
        else parent.appendChild(text);
      }
      continue;
    }

    if (existing && reusable(existing, vnode)) {
      update(opts, existing as ElLike, vnode);
      continue;
    }
    const made = create(opts, vnode);
    if (existing) parent.replaceChild(made, existing);
    else parent.appendChild(made);
  }

  // Anything past the end of the new list. Backwards, because removing shortens
  // the live NodeList underneath the loop.
  for (let index = parent.childNodes.length - 1; index >= wanted.length; index -= 1) {
    parent.removeChild(parent.childNodes[index]);
  }
}

function reusable(node: NodeLike, vnode: VNode): boolean {
  if (node.nodeType !== ELEMENT) return false;
  const el = node as ElLike;
  if (el.tagName.toLowerCase() !== vnode.tag.toLowerCase()) return false;
  // A keyed node may only be reused by the same key. An unkeyed one matches
  // anything of the same tag, which is what makes position-based reuse work for
  // the plain structural nodes.
  return (el.getAttribute(KEY_ATTR) ?? undefined) === vnode.key;
}

function create(opts: PatchOptions, vnode: VNode): ElLike {
  const el = opts.doc.createElement(vnode.tag);
  if (vnode.key) el.setAttribute(KEY_ATTR, vnode.key);
  update(opts, el, vnode);
  return el;
}

function update(opts: PatchOptions, el: ElLike, vnode: VNode): void {
  const keep = new Set<string>(vnode.key ? [KEY_ATTR] : []);

  for (const [name, value] of Object.entries(vnode.attrs)) {
    // `value` is a property, not an attribute: setting the attribute on an
    // input that already has one changes the default, not what is on screen.
    if (name === "value") {
      if (!opts.isFocused(el)) {
        (el as unknown as { value: string }).value = String(value ?? "");
      }
      continue;
    }
    // ARIA attributes are string enumerations, not boolean attributes.
    // `aria-pressed=""` is not `aria-pressed="false"`, and an *absent*
    // `aria-pressed` does not mean "not pressed" — it means "not a toggle
    // button", which is a worse thing to say about the slot grid than saying
    // nothing. So a false one is written out rather than dropped.
    const aria = name.startsWith("aria-");
    if (value === undefined || (value === false && !aria)) continue;
    keep.add(name);
    // Everything else follows HTML's rule, where presence alone is the truth:
    // `disabled=""` disables.
    const next = typeof value === "boolean" ? (aria ? String(value) : "") : String(value);
    if (el.getAttribute(name) !== next) el.setAttribute(name, next);
  }

  // Attributes the new tree does not want. Collected first: removing while
  // iterating the live NamedNodeMap skips entries.
  const stale: string[] = [];
  for (let index = 0; index < el.attributes.length; index += 1) {
    const name = el.attributes[index].name;
    if (!keep.has(name)) stale.push(name);
  }
  for (const name of stale) el.removeAttribute(name);

  opts.bind(el, vnode.on);
  patchChildren(opts, el, vnode.children);
}
