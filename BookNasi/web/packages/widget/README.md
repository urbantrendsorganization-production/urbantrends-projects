# @booknasi/widget

The booking flow, inside somebody else's page.

```html
<script src="https://booknasi.co.ke/widget/booknasi.js"
        data-shop="mint-braids-kilimani"
        data-api="https://api.booknasi.co.ke"></script>
```

```bash
npm run widget          # build -> web/public/widget/
npm run widget:check    # build, then the structural checks CI runs
```

Then open `/widget/demo.html` — a deliberately hostile fake host page that
mounts the widget twice, once as BookNasi ships it and once re-skinned.

## What this package is, and what it is not

CLAUDE.md §1 gives the product two front doors: a hosted booking page at
`shopname.booknasi.co.ke`, and an embedded module inside a `/site` template
whose client never sees BookNasi at all. Slice 5 put the flow in
`@booknasi/booking-core` so that the second door would be a **renderer** rather
than a **reimplementation**, and this package is the test of whether that
worked.

It did. Every decision here comes from a selector that already has tests:
`stepFor` chooses the screen, `offeredSlots` chooses the slots, `canContinue`
and `blockedReason` decide whether Continue is live and what it says when it is
not, `countdownLabel` decides what the timer says at zero. `view.ts` contains no
`if (payment.state === …)` and `check-widget.mjs` keeps it that way.

| | |
|---|---|
| `config.ts` | Everything a host may say. A closed list, and the reason it is closed. |
| `vdom.ts` | A node, and an action. About sixty lines. |
| `view.ts` | The eight screens, as pure data. |
| `css.ts` | The stylesheet, with the §10 invariants in literal pixels. |
| `patch.ts` | The reconciler. Takes a document so it can be tested without one. |
| `mount.ts` | The only file that touches a browser. |
| `index.ts` | The script tag's contract. |

## Why there is no React in here

Roughly 45 kB gzipped, before a screen exists, to draw eight screens of buttons
for a client on 3G whose success measure is sixty seconds from a WhatsApp link
to a paid deposit. There is no list virtualisation here, no animation system and
nothing concurrent; almost none of what that weight buys is used. And a host
page may already run React at a different version, where a second copy is
somewhere between wasteful and a hazard.

The whole bundle is **12 kB gzipped**, tokens and stylesheet included.
`check-widget.mjs` fails the build past 20 kB, so a date library or a validation
package is a decision somebody has to argue for rather than something noticed a
year later in a page-weight audit.

## The shadow root is how CLAUDE.md §10 survives a host page

A host stylesheet saying `#booking button { height: 36px }` is not malice — it
is a designer making their own site consistent, and it lands on the screen where
a mis-tap books the wrong time. Inside a shadow root that rule cannot select
anything.

What *does* cross the boundary is custom property inheritance, and that is the
half the design wants: it is how a host restyles the widget at all. So the
boundary is not a wall, it is a **valve — selectors out, named values in**,
which is the shape §10 describes. An iframe would block the values too and leave
the host unable to theme anything; a plain `div` would block nothing.

One consequence, deliberately: `.bn-root` inside the shadow root redefines every
`--bn-*` token, so a value inherited from the host page is shadowed rather than
used. Host overrides do not arrive by inheritance — `mount.ts` sets the ones
`config.ts` accepted as inline properties, where they win. The named list is
therefore the *only* channel, and a host who sets `--bn-space-gutter` on their
container changes nothing.

## What a host may change

Nine styling options and one copy token, all as `data-` attributes on the script
tag or keys in `BookNasi.mount(el, {…})`:

`shop` · `api` · `target` · `accent` · `accent-pressed` · `surface` · `canvas` ·
`border` · `radius` · `font-ui` · `font-display` · `label-case` ·
`deposit-word`

Anything else is ignored with a console warning — a typo must not take the
booking widget off a shop's page.

**Text colour is not on the list**, which is why a dark host site gets a light
widget panel and not a dark one. It looks like an oversight and is not: a host
who can set ink can set it to the surface colour, and the refund and forfeit
sentence that §10 says may be translated or relabelled **but never removed**
becomes removable, invisibly, with one hex value and complete deniability.

## What a host may never change

The four in CLAUDE.md §10, and they are unreachable by construction rather than
by rule:

1. **52 px targets** — in `css.ts`, in literal pixels, from
   `INVARIANTS.minTargetHeightPx`. Pixels and not `rem`, because `rem` is a
   multiple of the *host page's* root font size and a site running
   `html { font-size: 12px }` would silently shrink every target to 39 px with
   the invariant still correct in the token file.
2. **Three slot chips per row** — from `INVARIANTS.slotsPerRow`.
3. **The hold countdown stays visible** — `waitingPanel` is called
   unconditionally on every screen with a live hold, and renders
   `countdownLabel` rather than raw seconds, so zero-with-a-push-outstanding
   reads "Still checking with M-Pesa" instead of claiming an expiry the server
   has not declared.
4. **The `*334#` line** — from `INVARIANTS.ussdFallback`, never typed.

`check-widget.mjs` reads the *resolved* stylesheet for the first two, not the
source, because `min-height: ${INVARIANTS.minTargetHeightPx}px` proves only that
the constant is referenced. `build.mjs` evaluates `css.ts` and writes the real
CSS to `public/widget/stylesheet.css` for exactly that check.

## Cross-origin

The widget runs on the host's origin and calls the API on ours, so
`core/cors.py` answers `/api/public/` with `Access-Control-Allow-Origin: *`,
credentials never allowed, origin never reflected. The transport is constructed
with `credentials: "omit"` to match: this surface is unauthenticated and
shop-scoped by slug, it has no use for a cookie, and a widget that sent one
would be opening a credentialed cross-origin channel to an API with no idea what
to do with it.

## Failure is quiet on the host's page and loud in the console

A missing `data-shop` writes one line and renders nothing. Nothing here throws
past its own boundary: an uncaught error from a third-party script can take out
the host page's own scripts, and taking down a salon's website because their
booking widget is misconfigured is much worse than a booking widget that is not
there.
