# @booknasi/tokens

Single source of truth for colour, type, spacing, radii and motion. Extracted by
hand from `design/design_handoff_booknasi/BookNasi.dc.html` — the export is
inline-styled HTML with hardcoded hex, so there was no machine-readable token
file to import.

```bash
npm run build   # tokens.json -> dist/{tokens.css,tokens.ts,tailwind.js}
npm run check   # structural checks, runs in CI
```

Edit `src/tokens.json`. Never edit anything in `dist/`.

## Why the variables are scoped to `.bn-root`

Not `:root`. The standalone app puts `.bn-root` on `<html>`; the widget puts it
on its own mount container. A bare `:root` in the widget bundle would leak the
BookNasi palette into whatever page embedded it, and would turn every host
override into a specificity argument.

## Why Tailwind maps to `var()` and not to hex

The widget has to inherit a host site's colours **at runtime**. A default
Tailwind setup compiles `bg-clay-600` to `background: #C2521F`, which can never
be overridden by anything the host does. So the generated `tailwind.js` maps
every colour, radius and space step to `var(--bn-*)` instead.

The chain runs semantic-name-first:

```css
--bn-accent: #C2521F;          /* the host overrides this */
--bn-clay-600: var(--bn-accent); /* what Tailwind resolves */
```

Backwards, it would build cleanly and silently ignore every override. `check.mjs`
asserts the direction.

## What a host may override

Ten custom properties, set on the mount container:

`--bn-accent` · `--bn-accent-pressed` · `--bn-surface` · `--bn-canvas` ·
`--bn-border` · `--bn-font-display` · `--bn-font-ui` · `--bn-radius-md` ·
`--bn-label-case`

Plus the copy tokens in `COPY` — "deposit" reads wrong next to a luxury salon,
and the design's neutral-widget mock relabels it "reservation fee".

## What a host may never override

The four invariants in CLAUDE.md §10 — 52 px targets, the three-per-row slot
grid, the visible hold countdown, and the `*334#` fallback line. They ship as
constants in `INVARIANTS`, deliberately **not** as CSS custom properties, so no
host stylesheet can reach them. The refund/forfeit sentence may be translated or
relabelled but never removed.

## Deviations from the export

Three, all deliberate:

| | |
|---|---|
| `#EFE7DE` dropped | Design-canvas background — the colour behind the phone frames, not a product surface. Excluded so nobody reaches for it. |
| `#F1E7DE` named `--bn-track` | Used 22 times in the export with no name. It is the meter and progress-bar track on the owner dashboard. |
| Scales collapsed | Spacing went from 13 steps to 12 (9px folded into 10, 13 into 14); radius from overlapping numeric ranges to 8 named roles. Nothing in the design depended on a one-pixel difference, and `radius-md` needed a name because the host overrides it by name. |
