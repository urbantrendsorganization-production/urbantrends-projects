/**
 * The reconciler, against eighty lines of fake DOM.
 *
 * Worth the fake. A hand-written patcher fails in four ways and all four are
 * silent: an attribute that should have been removed and was not, a keyed node
 * rebuilt instead of reused, a text node left stale, and children left behind
 * when the new list is shorter. None of them throw; they just leave the screen
 * one render behind, which on the confirm screen is a client paying against a
 * price that has changed.
 *
 * The fake is deliberately dumb — no layout, no events, no CSS. It exists so
 * the *algorithm* can be tested, and the browser's own DOM is exercised by the
 * demo page rather than by a simulation of it.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { type DocLike, type ElLike, patchChildren } from "./patch";
import { type VNode, h, on } from "./vdom";

// ------------------------------------------------------------ the fake DOM

let created = 0;

class FakeText {
  nodeType = 3;
  constructor(public nodeValue: string | null) {}
}

class FakeEl {
  nodeType = 1;
  childNodes: (FakeEl | FakeText)[] = [];
  attrs = new Map<string, string>();
  value = "";
  /** A birth certificate. Reuse is asserted by identity of this number. */
  id = (created += 1);

  constructor(public tagName: string) {}

  get attributes() {
    return [...this.attrs.keys()].map((name) => ({ name }));
  }
  getAttribute(name: string) {
    return this.attrs.has(name) ? this.attrs.get(name)! : null;
  }
  setAttribute(name: string, value: string) {
    this.attrs.set(name, value);
  }
  removeAttribute(name: string) {
    this.attrs.delete(name);
  }
  appendChild(child: FakeEl | FakeText) {
    this.childNodes.push(child);
  }
  removeChild(child: FakeEl | FakeText) {
    this.childNodes = this.childNodes.filter((node) => node !== child);
  }
  replaceChild(next: FakeEl | FakeText, prev: FakeEl | FakeText) {
    this.childNodes = this.childNodes.map((node) => (node === prev ? next : node));
  }
}

const doc: DocLike = {
  createElement: (tag) => new FakeEl(tag) as unknown as ElLike,
  createTextNode: (value) => new FakeText(value),
};

function options(focused: FakeEl | null = null) {
  const bound: [FakeEl, VNode["on"]][] = [];
  return {
    opts: {
      doc,
      bind: (el: ElLike, listeners: VNode["on"]) => bound.push([el as unknown as FakeEl, listeners]),
      isFocused: (el: ElLike) => (el as unknown as FakeEl) === focused,
    },
    bound,
  };
}

function root() {
  return new FakeEl("div");
}

const at = (el: FakeEl, ...path: number[]) =>
  path.reduce<FakeEl>((node, index) => node.childNodes[index] as FakeEl, el);

// ------------------------------------------------------------------- tests

test("a tree is built once", () => {
  const parent = root();

  patchChildren(options().opts, parent as unknown as ElLike, [
    h("p", { class: "bn-note" }, ["Slot held for"]),
  ]);

  assert.equal(parent.childNodes.length, 1);
  assert.equal(at(parent, 0).tagName, "p");
  assert.equal(at(parent, 0).getAttribute("class"), "bn-note");
  assert.equal((at(parent, 0).childNodes[0] as unknown as FakeText).nodeValue, "Slot held for");
});

test("a second render reuses the node instead of rebuilding it", () => {
  // The countdown redraws once a second for three minutes. Rebuilding would
  // restart the progress bar's transition on every tick — the one animation
  // that has to be linear and honest.
  const parent = root();
  const tree = () => [h("p", {}, ["2:59"])];
  patchChildren(options().opts, parent as unknown as ElLike, tree());
  const first = at(parent, 0).id;

  patchChildren(options().opts, parent as unknown as ElLike, [h("p", {}, ["2:58"])]);

  assert.equal(at(parent, 0).id, first);
  assert.equal((at(parent, 0).childNodes[0] as unknown as FakeText).nodeValue, "2:58");
});

test("an attribute the new tree dropped is removed, not left behind", () => {
  const parent = root();
  patchChildren(options().opts, parent as unknown as ElLike, [
    h("button", { class: "bn-cta", disabled: true }, ["Pick a time first"]),
  ]);

  patchChildren(options().opts, parent as unknown as ElLike, [
    h("button", { class: "bn-cta" }, ["Hold my slot"]),
  ]);

  assert.equal(at(parent, 0).getAttribute("disabled"), null);
});

test("aria-pressed false is written, because absent means it is not a toggle at all", () => {
  const parent = root();

  patchChildren(options().opts, parent as unknown as ElLike, [
    h("button", { "aria-pressed": false }, ["10:00"]),
  ]);

  assert.equal(at(parent, 0).getAttribute("aria-pressed"), "false");
});

test("aria-pressed true is the string, not an empty boolean attribute", () => {
  // The CSS that draws selection reads `[aria-pressed="true"]`. HTML's boolean
  // rule would write `aria-pressed=""` and the chip would never look selected.
  const parent = root();

  patchChildren(options().opts, parent as unknown as ElLike, [
    h("button", { "aria-pressed": true }, ["10:00"]),
  ]);

  assert.equal(at(parent, 0).getAttribute("aria-pressed"), "true");
});

test("a keyed node is only reused by the same key", () => {
  const parent = root();
  patchChildren(options().opts, parent as unknown as ElLike, [
    h("button", { key: "service-braids" }, ["Braids"]),
  ]);
  const first = at(parent, 0).id;

  patchChildren(options().opts, parent as unknown as ElLike, [
    h("button", { key: "service-shave" }, ["Beard trim"]),
  ]);

  assert.notEqual(at(parent, 0).id, first);
});

test("an unkeyed node of the same tag is reused by position", () => {
  const parent = root();
  patchChildren(options().opts, parent as unknown as ElLike, [h("div", {}, ["a"])]);
  const first = at(parent, 0).id;

  patchChildren(options().opts, parent as unknown as ElLike, [h("div", {}, ["b"])]);

  assert.equal(at(parent, 0).id, first);
});

test("a changed tag is replaced rather than mutated", () => {
  const parent = root();
  patchChildren(options().opts, parent as unknown as ElLike, [h("p", {}, ["gone"])]);

  patchChildren(options().opts, parent as unknown as ElLike, [h("button", {}, ["here"])]);

  assert.equal(at(parent, 0).tagName, "button");
});

test("children the new tree does not want are removed", () => {
  // Six slots in the morning, then a date with two. The other four must go.
  const parent = root();
  const slots = (times: string[]) => times.map((time) => h("button", { key: time }, [time]));
  patchChildren(options().opts, parent as unknown as ElLike, slots(["07", "08", "09", "10", "11", "12"]));

  patchChildren(options().opts, parent as unknown as ElLike, slots(["07", "08"]));

  assert.equal(parent.childNodes.length, 2);
});

test("a nested subtree is patched in place", () => {
  const parent = root();
  const tree = (label: string) => [h("div", {}, [h("span", {}, [label])])];
  patchChildren(options().opts, parent as unknown as ElLike, tree("Slot held for"));
  const inner = at(parent, 0, 0).id;

  patchChildren(options().opts, parent as unknown as ElLike, tree("Your slot"));

  assert.equal(at(parent, 0, 0).id, inner);
  assert.equal((at(parent, 0, 0).childNodes[0] as unknown as FakeText).nodeValue, "Your slot");
});

test("an input's value is a property, and it is left alone while it has focus", () => {
  // Writing it back mid-number moves the caret to the end. This happens on the
  // confirm screen, one control away from the deposit.
  const parent = root();
  patchChildren(options().opts, parent as unknown as ElLike, [h("input", { value: "0712" }, [])]);
  const input = at(parent, 0);
  assert.equal(input.value, "0712");
  assert.equal(input.getAttribute("value"), null);

  input.value = "0712345";
  patchChildren(options(input).opts, parent as unknown as ElLike, [h("input", { value: "0712" }, [])]);

  assert.equal(input.value, "0712345");
});

test("an unfocused input is brought back into line with the state", () => {
  const parent = root();
  patchChildren(options().opts, parent as unknown as ElLike, [h("input", { value: "0712" }, [])]);
  const input = at(parent, 0);
  input.value = "typed by nobody";

  patchChildren(options().opts, parent as unknown as ElLike, [h("input", { value: "0712" }, [])]);

  assert.equal(input.value, "0712");
});

test("the action map is refreshed even when the element is reused", () => {
  // The same chip on a different day is the same node and a different slot.
  const parent = root();
  const chip = (startsAt: string) =>
    on(h("button", { key: "chip" }, ["10:00"]), "click", { type: "chooseSlot", startsAt });

  const first = options();
  patchChildren(first.opts, parent as unknown as ElLike, [chip("2026-09-09T07:00:00Z")]);
  const second = options();
  patchChildren(second.opts, parent as unknown as ElLike, [chip("2026-09-10T07:00:00Z")]);

  assert.deepEqual(second.bound[0][1].click, {
    type: "chooseSlot",
    startsAt: "2026-09-10T07:00:00Z",
  });
});

test("the key attribute survives an update and is not treated as stale", () => {
  const parent = root();
  patchChildren(options().opts, parent as unknown as ElLike, [h("button", { key: "phone" }, ["a"])]);

  patchChildren(options().opts, parent as unknown as ElLike, [h("button", { key: "phone" }, ["b"])]);

  assert.equal(at(parent, 0).getAttribute("data-bn-key"), "phone");
});

test("nulls and falses in a child list are not rendered as anything", () => {
  const parent = root();

  patchChildren(options().opts, parent as unknown as ElLike, [
    h("p", {}, ["kept"]),
    null,
    false,
    h("p", {}, ["also kept"]),
  ]);

  assert.equal(parent.childNodes.length, 2);
});
