# Handoff: BookNasi — deposit-first appointment booking

> **Amended 1 Aug 2026, post-handoff.** Three corrections against the original export: the
> scope line below said "clinics" (no clinic screens exist in the canvas and clinics are
> deliberately deferred — see `CLAUDE.md` §8); `#F1E7DE` was used 22 times but undocumented;
> and `canvas` needed a stronger exclusion note. Nothing else has been changed.

## Overview

BookNasi is a web platform for Kenyan salons and barbershops. Clients book from a
public link (usually shared over WhatsApp) and pay a **deposit by M-Pesa** at the moment of
booking; the deposit is the product's reason to exist, because no-shows are the problem it
solves. Staff use a single mobile screen to read today and record walk-ins. Owners run one
or more shops from a desktop dashboard whose job is to justify the subscription.

Three users, three different design problems:

| User | Device / posture | Jobs | Success measure |
|---|---|---|---|
| Client | Own phone, 3G, arrives cold from a link, no account | Book and pay a deposit | Link → paid deposit in under 60 s |
| Staff | Shop phone, standing, one hand, wet hands | See today; record a walk-in in 3 taps | Beats the paper notebook |
| Owner | Desktop/tablet, sitting, weekly | See that deposits reduced no-shows | Renews the subscription |

Tenancy: one **organisation** owns many **shops**; each shop has **staff**, **services**
(with per-service deposits) and its own booking link. One login and one bill per org.

## About the design files

`BookNasi.dc.html` in this bundle is a **design reference created in HTML** — a prototype
showing intended look, copy and states. It is **not production code to lift**. The task is to
recreate these designs in the target codebase's existing environment (React, Vue, Svelte,
native, etc.) using its established component library, routing and data patterns. If no
codebase exists yet, pick the appropriate stack for a mobile-web-first product with a
server-side payment webhook (e.g. Next.js + Postgres) and implement the designs there.

The file is a static design canvas: every screen is drawn side by side, phone frames are
390 × 812 mock viewports, and nothing is interactive. Read it for layout, exact values and
copy. **Annotation cards in clay/red/green tint are design rationale, not UI** — do not build them.

## Fidelity

**High fidelity.** Colors, type, spacing, radii, copy and state coverage are final and
intended to be matched. Two qualifications:

- No logo mark exists — the wordmark is "BookNasi" set in Bricolage Grotesque 700 only.
- No photography is used anywhere. If shop photos are wanted, the service card needs rework.

---

## Design tokens

### Color

Warm neutrals carry the entire product; one accent; three semantic families.

| Token | Hex | Use |
|---|---|---|
| `clay-50` | `#F6E9E1` | Accent tint: selected card fill, annotation panels, focus halo |
| `clay-200` | `#E9BFA5` | Avatar fill, dark-surface accent text |
| `clay-400` | `#D97742` | Charts only |
| `clay-600` | `#C2521F` | **The accent.** Primary buttons, selected state, active data bars |
| `clay-700` | `#A34117` | Pressed primary, accent text on tint |
| `clay-900` | `#6E2A0E` | Avatar text on `clay-200` |
| `white` | `#FFFFFF` | Cards, sheets, headers, primary surface |
| `paper` | `#FBF7F3` | Phone body background, table header rows, sunken panels |
| `canvas` | `#EFE7DE` | Design-canvas background only. **Excluded from `tokens.json` — never ships.** |
| `line` | `#E8DFD6` | Hairlines, dividers, disabled fills |
| `line-strong` | `#D6C8BB` | Default 1.5px borders on inputs, cards, chips |
| `track` | `#F1E7DE` | Meter and progress-bar track (owner dashboard load meters, utilisation bars). Ships as `--bn-track`. |
| `ink-45` | `#8E7C6E` | Meta text, labels, placeholders (4.6:1 on white) |
| `ink-70` | `#574A41` | Body text |
| `ink` | `#1F1712` | Headings, primary text, dark buttons |
| `ink-disabled` | `#A2948A` | Disabled button label on `line` |
| `pay-600` | `#1E8E3E` | M-Pesa green — **payment moment only** |
| `pay-700` | `#146C2F` | Green text on tint, success toast fill |
| `pay-50` | `#E6F2E8` | Paid badge fill, refund panels |
| `pay-dark` | `#3FBB63` | Green on the dark STK screen |
| `hold-600` | `#B26A00` | Pending / held / timer |
| `hold-700` | `#8A5200` | Hold text on tint |
| `hold-50` | `#FBEFD9` | Held-slot panel fill |
| `fail-600` | `#AF1B24` | Failure, no-show, destructive |
| `fail-700` | `#8E1219` | Failure text on tint |
| `fail-300` | `#E7A9A6` | Destructive borders |
| `fail-50` | `#FBE7E6` | Failure panel and badge fill |
| `info-600` | `#3D5A6C` / `#2C4655` | Offline, neutral information |
| `info-50` | `#E7EDF1` | Offline panel fill |
| `stk-bg` | `#0F2A18` | The one inverted screen (STK waiting) |

Dark theme is **noted, not built** — no dark screens exist. Tokens to use if it is built:
bg `#14100D`, surface `#1F1712`, border `#3A2E26`, ink `#F2EAE2`, accent `#E0703C`
(lifted for contrast on dark), pay `#3FBB63`, fail `#E5545C`.

**Accent discipline (enforce in review):** `clay-600` appears on exactly one element per
screen — the action that moves the booking forward. Selection uses `clay-50` fill + 2px
`clay-600` border, never a second filled clay button. Money already paid is green; money
still owed is neutral. The **owner dashboard has no primary action and therefore no clay
button at all** — clay appears there only as data bars.

M-Pesa green is reserved for the payment moment (STK screen, paid badge, paid amount,
refund confirmation). Do not use it as a generic success color.

### Type

| Family | Weights | Use |
|---|---|---|
| Bricolage Grotesque | 600, 700 | Display: screen titles, section headings, avatar initials |
| IBM Plex Sans | 400, 500, 600, 700 | All UI: lists, forms, labels, body |
| IBM Plex Mono | 400, 500, 600 | **Money and times only**, plus receipt/reference codes |

Google Fonts: `Bricolage+Grotesque:opsz,wght@12..96,400..800`,
`IBM+Plex+Sans:wght@400;500;600;700`, `IBM+Plex+Mono:wght@400;500;600`.
The neutral-widget mock additionally uses `Jost:wght@200;300;400;500` — that is the fake
host brand's font, not a BookNasi font.

Scale (mobile values; these are the sizes shipped, not scaled-down desktop values):

| Role | Size / line-height | Family & weight | Notes |
|---|---|---|---|
| Display | 32 / 36, `-0.02em` | Bricolage 700 | Confirmation headline, screen title |
| Display sm | 30 / 34 | Bricolage 700 | Error and timeout headlines |
| Title | 22 / 28, `-0.01em` | Bricolage 600–700 | Step titles, card headings |
| Body L | 17 / 24 | Plex Sans 400–600 | Service names, primary rows, button labels |
| Body | 15 / 22 | Plex Sans 400 | Supporting copy |
| Body sm | 13.5–14 / 1.5–1.6 | Plex Sans 400 | Helper text, notes |
| Label | 13 / 16, `0.06em`, uppercase | Plex Sans 600 | Section labels ("Morning") |
| Micro label | 11–12.5, `0.04–0.1em`, uppercase | Plex Sans/Mono 600 | Status, table headers |
| Money | 20 / 24 (up to 26) | Plex Mono 600, `tabular-nums` | Always `KES 1,000`, never `1.5k` |

Rules: nothing below 15 px in client or staff views (13 px only for uppercase labels);
`text-wrap: pretty` on any wrapping prose; long service names wrap to two lines and are
never truncated on the client side; staff rows may `text-overflow: ellipsis` after two lines.
Times are 12-hour with a space (`10:00 am`); durations are spelled (`3 hr 30 min`).

### Spacing, radius, elevation

- Spacing scale actually used: 4, 6, 8, 9, 10, 12, 14, 16, 18, 20, 22, 24, 28 px. Screen
  gutters 20 px on phone, 22–24 px on desktop panels. Vertical rhythm inside a screen is
  `gap: 12–16px`; between canvas sections 28 px.
- Radius: `8px` chips/badges · `9–11px` small controls · `12px` buttons and inputs ·
  `13–14px` cards · `16–18px` panels · `20–22px` bottom sheets (top corners only) ·
  `28px` phone frame · `999px` pills and avatars.
- Borders: `1px #E8DFD6` on structural panels; `1.5px #D6C8BB` on interactive resting
  elements; `2px #C2521F` on selected/focused, plus `box-shadow: 0 0 0 3–4px #F6E9E1`.
- Elevation: cards are flat (border only). Sheets `0 -18px 40px -20px rgba(31,23,18,.4)`.
  FAB `0 10px 24px -6px rgba(194,82,31,.6)`.
- Targets: 52 px standard control height; 56–62 px primary CTA on staff screens; **64–72 px
  rows on the walk-in flow** (the wet-hands screen); 44 px absolute minimum for text buttons.

### Component states to implement

- **Button, primary:** default `clay-600` / white; pressed `clay-700` + `scale(0.985)`;
  pending — spinner + label states the truth ("Sending request…"), never a bare spinner;
  disabled `line` fill / `ink-disabled` text and the label **says why** ("Pick a time first").
- **Button, secondary:** white, 1.5px `line-strong`, ink label. **Destructive:** `fail-50`
  fill, 1.5px `fail-300`, `fail-700` label — never clay.
- **Input:** 52 px, 12 px radius, 1.5px `line-strong`; focus 2px `clay-600` + 4px `clay-50`
  halo; error 2px `fail-600` with message below in `fail-600` 13 px 500. Phone inputs show a
  fixed `+254` prefix in mono, divided by a hairline, and the 9 remaining digits in mono.
- **Time-slot chip:** 52 px, 3 per row, 9–10 px gap, mono 15.5 px. Six states: available
  (white/`line-strong`) · selected (`clay-600` fill + halo) · unavailable (dashed `line`,
  `paper` fill, struck-through) · **just-taken** (`fail-50` fill, `fail-300` border, two-line
  chip with "JUST TAKEN" micro-label) · hover · pressed.
- **Service card:** name (17/1.35, may wrap two lines) + mono price right-aligned on the
  same baseline row; second row = mono duration · deposit pill (`clay-50`/`clay-700`) or
  plain "No deposit needed" in `ink-45`. Selected = 2px clay + `clay-50` fill + halo.
- **Staff avatar:** 46–64 px circle, `clay-200`/`clay-900` for the current user, `line`/`ink-70`
  for others, initials in Bricolage 600. Availability dot 15–18 px, bottom-right, 2.5–3 px
  white ring: green free, amber busy, `ink-45` on leave (whole cell at 55 % opacity).
  "Anyone" is a dashed clay circle reading `ANY / ONE`.
- **Appointment row:** left column = mono time (fixed 66–74 px, so the column never shifts),
  then a divider, then service name (may wrap) + client/meta, then right-aligned status +
  payment badge. Four variants: upcoming (white) · in progress (2px clay + halo + 3px clay
  spine) · completed (`paper`, muted) · no-show (`fail` tinted, struck name).
- **Payment badges:** paid `pay-50`/`pay-700` with amount · awaiting `hold-50`/`hold-700`
  with a live countdown · failed, forfeited `fail-50`/`fail-700` · none, cash `line`/`ink-70`
  · refunded `info-50`/`info-600` · "Balance KES 2,500 at shop" outlined.
- **Toasts:** bottom, above the thumb, 4 s, 14 px radius. Ink for progress, `pay-700` for
  success, `fail-700` for failure with an inline retry link, `info-600` for offline.
- **Empty states:** dashed `line-strong` panel, Bricolage 22 px heading, one sentence of
  guidance, one action. Always name the next real option ("Wanjiku's next opening is
  Fri 7 Aug, 8:00 am") rather than a generic apology.

---

## Screens

Grouped as they appear on the canvas. Frame = 390 × 812.

### 01 Design system
Reference only — palette, type specimens, and every component state above. Nothing to build.

### 02 Client booking flow (8 screens)

**1 · Service list.** Shop header (44 px rounded-square logo, shop name in Bricolage 20,
"Open until 8:00 pm · Wood Ave" in `ink-45`), then a `pay-50` reassurance strip: "Deposit by
M-Pesa holds your slot. Refundable up to 24 hr before." Title "What are you booking?" with
`1 / 4` in mono at the right. Service cards, deposit priced on every card **before anything
else is asked**.

**2 · Staff.** Back bar shows the chosen service truncated + mono "3 hr 30 min · KES 3,500".
Title "Who with?". "Anyone available" is first and pre-selected, subtitled "Soonest: today
10:00 am". Each stylist row carries their own duration for this service (Wanjiku 3 hr 30,
Grace 4 hr 15) — per-staff durations are real and must drive availability. On-leave rows are
55 % opacity with the return date. Footnote: "Times differ by stylist".

**3 · Slot picker.** Horizontal day strip (60 px cells, ink fill for selected, dashed for
closed days). Slots grouped "Morning" / "Afternoon", 3 per row, only starts that fit the
**full** duration are offered. Footnote states the finish time ("Ends about 1:30 pm").
Sticky footer: "Deposit now KES 1,000" + `Continue · Thu 10:00 am`.

**4 · Confirm & pay.** Three stacked cards — appointment summary; money (total / **deposit
now** / balance at shop) with the refund rule *inside the same card*; M-Pesa number input.
CTA `Pay KES 1,000 deposit`, sub-caption "You'll get an M-Pesa prompt on this phone".
The refund and forfeit rule is stated **before** payment, never after.

**5 · STK waiting** — the only inverted screen in the product, `#0F2A18`. Pill "M-PESA
REQUEST SENT", Bricolage 34 headline "Check your phone for the M-Pesa prompt", mono
"KES 1,000 to Mint Braids" in `pay-dark`. Numbered 3-step list on a connector rail:
(1) leave this page open, (2) enter your PIN — **includes the `*334#` USSD fallback**,
(3) come back here. Bottom: held-slot countdown `1:42` with a progress bar, "Resend the
prompt" outlined, "Pay at the shop instead" as quiet text.

**6 · Confirmed.** Green check, "Booked. Deposit received.", then the M-Pesa reference code
in a `pay-50` pill (`KES 1,000 paid · M-Pesa SJ42K19XQ`) — **the code comes before
everything else because it is the proof at the door**. Detail card with mono date/time 26 px,
service, stylist, balance owing, Directions link. Actions: add to calendar, share on WhatsApp.
Footnote: SMS + reminder schedule + cancel window.

**7 · Payment failed.** Names the Safaricom reason verbatim ("insufficient funds") and states
"Nothing was taken from your account." `hold-50` panel keeps the countdown visible and alive.
Three ways out: try again · different number · ask the shop to hold. Then an offer of
deposit-free services. Closes with "Nothing is booked yet."

**8 · Timed out.** Slot released. Promises automatic refund within 24 hr if money did leave.
Offers the same stylist's remaining slots as chips, then `Start again at 12:00 pm`. Footer
gives the shop's WhatsApp number **and a support code** (`BK-40219`) for payment disputes.

### 02b Variations (decisions already made — build the recommended one)

- **Deposit moment:** A sheet-over-grid ✅ recommended · B full review page (fallback when
  the sheet would scroll) · C hold-now-pay-in-10-min ❌ not for v1 (reintroduces the no-show).
- **Slot picker:** A period grid ✅ recommended · B duration rail (better inside staff views)
  · C soonest-first shortcut (sits *above* A, does not replace it).

### 03 Staff

**Today (my chair).** Header: avatar + "Wanjiku · today" + date/shop; three stat tiles
(appointments · **KES deposits in**, green · walk-ins). Body is not a calendar — it is three
bands: **Now** (clay heading and rule) / **Next** / earlier work sunk to `paper` grey.
The in-progress row shows elapsed time and gets `Finish now` (ink) + `Running late`
(secondary) directly beneath it. **No tab bar, no hamburger, no week view** — everything else
lives behind the avatar. A 64 px clay FAB (`+`) is pinned bottom-right over a fade and never
scrolls away.

**Appointment detail.** In-progress card (mono `10:00 am → 1:30 pm`); Payment block with
paid badge, M-Pesa code, paid timestamp, service total, then **`Collect now KES 2,500`** in
clay mono 22 px above `Mark balance collected`; Client block with call button and history
("4th visit · no no-shows"); footer `Reschedule` + `No-show` (destructive).

**Walk-in — 3 taps.** Tap 1 service (64 px rows, this staff member's five most-recorded
services first, then "Something else"). Tap 2 who — **"Me" is first and pre-selected**, others
show when they're free. Tap 3 confirm: mono `11:04 am → 12:34 pm`, price, "Deposit — Not for
walk-ins", 56 px `Start · 11:04 am`, plus optional `Add name` / `Waiting, not started`.
Name and phone are asked **after** saving, never before. Writes optimistically: row appears
immediately, toast reports the sync. **Walk-ins never take a deposit.**

### 04 Owner (1320 px desktop)

Top bar: wordmark, org switcher (shows shop count), tabs Overview/Appointments/Clients/
Staff/Settings, EAT clock, date-range picker. Headline states the conclusion, not the metric:
"Deposits are working".

Cards: **no-show rate before vs after deposits** as two bars (18.4 % grey → 7.1 % green) with
deposits taken, deposits forfeited ("money that used to be zero") and STK completion beside
it; **today across shops** as load meters with an adoption warning ("Thika Rd has recorded no
walk-ins in 9 days"); **repeat clients** with trend.

**Revenue per staff table:** staff · services · revenue · deposits · no-shows · utilisation
bar. Ordered by revenue, but the argument lives in the deposit column — the barber with no
deposits has 7 no-shows against everyone else's ≤ 2. Keep deposits and no-shows adjacent.

Also: **Overview variation B** (same four numbers reframed as the questions an owner asks —
better on tablet / for a first-time owner) and the **shop switcher** (each shop shows today's
load and staff count; a struggling shop is flagged in the switcher itself; subscription
status and renewal price in the footer).

### 05 Shop settings & staff

Sidebar (shop scope: services & deposits, hours, staff, booking page, notifications; org
scope: shops, billing, data & privacy). **Services table** with per-service deposit and
inline per-staff duration overrides. **Deposit editor** panel: flat KES / % of price / none;
amount with live "29 % of KES 3,500 · balance KES 2,500 at the shop"; cancellation policy
(refund over 24 hr / credit only); and a **preview of the exact sentence the client will
read** — the rule and its wording are edited in one place. Flat KES is the default mode.
**Hours** with per-day toggles, buffer between services (10 min), and **hold-unpaid-slots-for
(3 min)** — the STK window. **Staff list** doubles as an adoption report: skills, hours, leave
(a leave block removes availability *and* notifies booked clients — the row says so), and
`Invited 3 Aug · hasn't signed in yet` with a resend action.

### 06 Neutral widget

The same flow re-tokenised into a fake host brand (near-black, off-white, square corners,
Jost 200/400, uppercase `0.22em` labels, "reservation fee" instead of "deposit"). Three
frames: service list, deposit sheet, waiting state. Host overrides accent, surface, canvas,
border, radius, fonts and label casing; **"deposit" itself is a copy token**.

Four things never tokenise: the 52 px target height, the 3-per-row slot grid, the visible
hold countdown, and the `*334#` fallback line. The refund/forfeit sentence may be translated
or relabelled but not removed.

### 07 Lifecycle

**Manage booking** (opened from the SMS link, no login): confirmed badge, mono date/time,
amounts paid and owing, a `pay-50` panel stating the free-change deadline, then
`Move to another time` (clay) / `Get directions` / `Cancel booking` (destructive).

**Cancel — in window:** sheet stating the refund first (amount, destination number,
"usually within an hour", confirming SMS), optional reason chips, then
`Move it instead` as the clay button **above** `Cancel and refund me`.

**Cancel — inside 24 hr:** `fail-50` panel, "Your KES 1,000 deposit — Not refunded", the
rule restated, and the rescue path as primary: `Move — keep my KES 1,000`, then
`WhatsApp the shop`, with "Cancel and lose the deposit" demoted to quiet text.

**Message templates** — SMS is the real interface. Client: confirmed (with M-Pesa ref and
manage link), 24 hr reminder, 2 hr reminder, refunded, missed. Staff/owner: new booking push,
cancelled push, 7:00 am day start, Monday weekly digest. Rules: time and place in the first
clause, money as a plain KES figure, exactly one link, no greeting/sign-off/emoji, sender ID
`BOOKNASI`.

**Client data & privacy** (owner, Kenya DPA 2019): export client list as CSV; delete a
client's identity **while keeping the appointment as an anonymous record** so revenue stays
correct; retention period (24 months default); marketing off by default with opt-in at
booking. Both DPA requests arrive by phone because clients have no login — the owner must be
able to serve them here in under a minute.

**Owner onboarding**, four steps, ordered so the shop is **bookable after step 3**:
(1) shop name/address/hours → (2) five services with duration, price, deposit — advice
("about a quarter of the price") in prose, **nothing pre-filled** → (3) connect M-Pesa
Paybill/Till → (4) invite staff by SMS. The shop's booking URL is shown in the footer from
step one onward.

---

## Interactions & behaviour

- **Step navigation** 1→4 is real routing with its own URL per step; the back arrow returns
  to the previous step with all selections intact.
- **Slot hold.** Continuing from step 3 puts the slot in `pending_payment` with a TTL
  (shop-configurable, default 3 min) and starts a **visible** countdown. The countdown is the
  reason it's safe to ask a client to leave the page — never hide it. On expiry the server
  releases the slot and the client screen must say so before they find out at the shop.
- **STK push.** The confirm CTA fires an STK push and immediately navigates to the dark
  waiting screen (never a spinner over the form). The waiting screen polls (or subscribes)
  for the payment result and rewrites itself into confirmed / failed / timed-out. Resend is
  rate-limited; expose `*334#` as the fallback in the copy.
- **Payment truth comes from the server webhook**, not the client. A late callback after a
  timeout must still confirm the booking and send the SMS — the timeout screen explicitly
  tells the client not to pay twice and gives them a support code.
- **Just-taken collision.** A losing confirm turns *that chip* `fail`-tinted in place; the
  rest of the grid stays live and no entered data is lost. Never a full-page error.
- **Walk-in collision.** If a walk-in overlaps an existing booking, tap 3 becomes a single
  choice ("shorten to 12:00" / "give it to Brian") — never a validation error above a form.
- **Offline.** Staff writes go to a local queue and render immediately with a pending dot;
  toast reports the sync. A staff action must never block on the network. Stale reads show
  "Today's list is from 9:12 am. It will refresh by itself."
- **Optimistic UI is for staff only.** The client's deposit is never shown as paid until the
  webhook confirms it.
- **Transitions:** step changes 200 ms ease-out slide; sheets 240 ms ease-out from the bottom
  with a scrim; toasts 160 ms fade-and-rise, auto-dismiss 4 s; the countdown bar animates
  linearly, no easing. Respect `prefers-reduced-motion` by cross-fading instead.
- **Responsive.** Client and staff are mobile-first and cap at ~480 px centred on desktop;
  the owner dashboard is desktop/tablet from 1024 px up (below that, the staff view is the
  correct experience). The widget must survive an arbitrary host container width.

## State

Client booking machine: `browsing → serviceChosen → staffChosen → slotChosen →
detailsEntered → holdCreated(ttl) → stkPushed → { paid | failed(reason) | timedOut |
slotLost }`. Client state per session: `shopId, serviceId, staffId | 'anyone', slotStart,
phone, holdId, holdExpiresAt, paymentRef`.

Server-owned truth: slot inventory per staff per day (derived from hours − buffer − existing
bookings − leave, using **per-staff service durations**), hold TTLs, payment status from the
M-Pesa webhook, refund status, forfeit records. Booking status:
`pending_payment | confirmed | completed | cancelled_refunded | cancelled_forfeited |
no_show | walk_in`.

Staff view: today's appointments for the signed-in staff member only (personal logins), a
local write queue, and a connectivity flag. Owner view: date range, shop scope, cached
aggregates — no realtime requirement.

Data fetching: the public booking page must render on a slow 3G connection — server-render
the shop and service list, fetch availability per day on demand, and keep the payload small.

## Assets

None. No images, no icon font, no illustration. The handful of glyphs in the mock
(`←  ✓  ✕  ⋯  ☎  ≡  ⏱  ›`) are placeholders — substitute the codebase's icon set at the
sizes shown. Fonts come from Google Fonts (self-host in production). Avatars are initials on
a tinted circle, not photos.

## Files

- `BookNasi.dc.html` — the full design canvas: design system, client flow (8 screens),
  variations, staff (today / detail / walk-in), owner (dashboard / switcher / settings /
  staff), neutral widget, and lifecycle (manage / cancel / messages / privacy / onboarding).
- `support.js` — runtime for the design file only. **Not part of the deliverable.**

## Open, for the product owner

No logo mark (wordmark only). No photography. Dark theme has tokens but no screens.
Out of scope for v1 and deliberately not designed: multi-service baskets, staff commission
splits, retail/product sales, loyalty schemes.
