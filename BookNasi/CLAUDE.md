# CLAUDE.md

Guidance for Claude Code when working in this folder.

---

## 1. What this project is

BookNasi is appointment booking for Kenyan salons and barbershops. Django/DRF backend, Next.js frontend, Postgres + Redis + Celery, M-Pesa deposits.

It has to serve two front doors from one codebase:

1. **Standalone SaaS** — owner signs up, gets a hosted booking page at `shopname.booknasi.co.ke`.
2. **Embedded module** — a `/site` (TechMtaani) template embeds the booking widget; the client never sees BookNasi branding.

**Build every API as if a third party will integrate it, because one will.** The core knows nothing about templates, themes, or the `/site` shell. No `/site`-specific branches in domain code.

The product being sold is not the calendar. It's the **M-Pesa deposit** that turns a no-show from a total loss into partial payment. Prioritise accordingly.

---

## 2. Stack and commands

| Layer | Choice |
|---|---|
| Backend | Django + DRF, Python managed with `uv` |
| DB | PostgreSQL (needs `btree_gist`) |
| Cache / broker | Redis |
| Async | Celery + Celery Beat |
| Frontend | Next.js + TypeScript, mobile-first |
| Local | docker-compose |
| Deploy | GitHub Actions → GHCR → Hetzner, Caddy in front, containers bound to `127.0.0.1` |

```bash
uv sync                              # install backend deps
docker compose up -d                 # postgres, redis, api, worker, beat
uv run python manage.py migrate
uv run python manage.py test         # or pytest, per repo config
uv run ruff check . && uv run ruff format .
npm run dev                          # frontend
```

---

## 3. Data model — non-negotiable shape

```
Organization        billing, owner, subscription state
└ Shop              location, hours, branding, booking page
  ├ Staff           working hours, skills, leave
  ├ Service         name, duration, price, deposit rule
  └ Appointment     client, staff, service, time range, status, payment
Client              belongs to Organization, NOT Shop
```

Two rules that are expensive to reverse:

- **Client belongs to the Org.** A regular who visits two branches must be one person with one history. Never scope `Client` to a `Shop`.
- **Service duration is per-service, overridable per staff member.** A senior stylist does in 30 min what a junior takes 50 for. If the schedule can't express that, the calendar lies and staff stop trusting it.

Every tenant-scoped query filters by org. There is no such thing as a cross-org read outside of admin tooling.

---

## 4. The availability engine — where this build will go wrong

Everything else here is CRUD. Scheduling is not. Treat this module as the highest-risk code in the repo and test it hardest.

Availability is **derived, never stored**:

```
shop opening hours
  − staff working hours
  − staff leave
  − existing appointments
  − buffer between services
  − service duration (staff-specific)
```

Rules:

- Compute server-side. **Never trust a client-supplied slot as valid** — always re-derive on write.
- Cache per `(staff_id, date)` in Redis. Invalidate on any write that touches that staff-day: appointment create/cancel/reschedule, leave, working-hour change, service duration change.
- Store UTC, render EAT. Single timezone, no DST — do not build a timezone abstraction layer.

### Double-booking is prevented at the database, not in Python

Two clients tapping "confirm" in the same second both pass an application-level `if slot_is_free` check. Enable `btree_gist` and add an exclusion constraint on `appointments`:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE appointments ADD CONSTRAINT no_overlapping_appointments
EXCLUDE USING gist (
    staff_id WITH =,
    time_range WITH &&
) WHERE (status IN ('pending_payment', 'confirmed', 'in_progress'));
```

Catch the `IntegrityError` and return a clean "just taken, pick another slot." Do not replace this with a lock, a queue, or a `select_for_update` and call it done — the constraint stays regardless of what else you add.

### Walk-ins are v1, not v2

In Kenya walk-ins are the majority. If staff can't record one in **three taps**, they won't, the calendar drifts from reality, and online bookings start colliding with people already in the chair. Any change that adds friction to walk-in entry is a regression.

---

## 5. Payments — M-Pesa deposits

- STK push fires at booking confirmation for the deposit portion. Slot is held as `pending_payment` with a short TTL, released by a Celery job if the callback never arrives.
- **Callbacks must be idempotent.** Safaricom retries. Unique constraint on the checkout request ID; process exactly once. Duplicate processing means double-charging or double-booking.
- Deposit rules live on the service: flat amount, percentage, or none (a quick shave shouldn't need one). The shop sets the rule; service creation pre-fills **25%**, so charging nothing is a deliberate change rather than the path of least resistance.
- **A service with no deposit is not publicly bookable in v1.** Staff can book it and it can be recorded as a walk-in, but the public booking page and the public API must both reject it. There is no client account and no OTP — the STK push *is* the phone verification, so a deposit-free public booking is an unverified number holding a slot for free. Enforce this at the API, not only in the UI.

- **The carve-out: a booking backed by an already-succeeded payment needs no new push.** Added at slice 7. Two paths produce a confirmed public booking with no STK prompt of its own, and neither is the thing the rule above forbids:

  1. **A re-pointed payment** — the `slotLost` remedy. The client paid, the callback was slow, the slot went, and they pick another time. The same succeeded payment is carried to the new appointment (`payments/repoint.py`, with a `PaymentMove` row recording the pair).
  2. **A deposit covered entirely by shop credit** — a late cancellation's credit, spent on a rebooking (`payments/credit.py`).

  The rule exists to stop **unverified numbers** holding slots. In both cases Safaricom already confirmed a payment from that number, and a succeeded payment *is* the verification the deposit rule was standing in for. Satisfying the rule's purpose through the payment it was a proxy for is not a loophole in it.

  What stays true: the money must be real and traceable. A credit is `PROTECT`-linked to the payment it descends from, a re-point requires `PaymentState.SUCCEEDED`, and neither path can be reached with a request alone — each needs a money record only a real M-Pesa success could have produced. A deposit-free *service* is still not publicly bookable, and nothing here relaxes that.
- The deposit is applied to the final bill, not held separately.
- Refund/forfeit is a product decision, not a technical one, but the policy must be visible to the client **before** they pay. Otherwise every forfeit becomes a support ticket.
- Design payment records so a transaction-fee model stays possible later. Don't implement it now.

Never log full M-Pesa payloads with phone numbers at INFO. Never commit shortcode credentials — sandbox or live.

---

## 6. Notifications

- Confirmation on booking, reminder at T-24h and T-2h, cancellation notice.
- Reminders are Celery tasks keyed to the appointment. **Cancel the task when the appointment is cancelled** — clients getting reminded about appointments that no longer exist is a trust bug, not a cosmetic one.

  Built at slice 8. This line and §8's "confirmation + one reminder" disagreed; settled in favour of two, because this section's own cost arithmetic prices three messages a booking. The qualification that nearly reconciles them: **a reminder whose moment has already passed is never armed**, so a booking made six hours out costs one reminder and one made ninety minutes out costs none. They do different jobs — T-24h is the last moment a cancellation is refundable rather than credit under §12, so it frees a resellable slot; T-2h is the one that stops somebody simply forgetting.

  Two mechanisms, as with hold release: an `eta` task for timeliness and a five-minute Beat sweep for correctness. Unlike hold release, the `eta` is armed only inside a one-hour horizon — a Celery `eta` weeks out is a promise held in a worker's memory for weeks, lost on every restart, and a reminder five minutes late is still a reminder. The sweep also arms reminders for confirmed bookings that have none, so a confirmation path that forgets to call in costs a delay rather than a silence.

  Nothing is sent before **07:00 EAT**. Only the T-2h can land earlier, and it shifts forward rather than being dropped.
- Messaging cost is a real line item (300 bookings × 3 messages = 900/month on the cheapest tier). Keep the provider behind an interface so SMS → WhatsApp Business API is a swap, not a rewrite.

---

## 7. Two audiences, one product

- **Staff view** must be faster than the notebook for the two things they do all day: see today's list, add a walk-in. That's the adoption bar.
- **Owner dashboard** (revenue per stylist, no-show rate, repeat client rate) is what renews the subscription.

Build the owner dashboard, but **never at the cost of the staff view**. If staff stop using it, the subscription churns in three weeks regardless of how good the analytics look.

---

## 8. MVP scope

**In:**
- Org + shop creation, staff and service setup
- Public booking page per shop, mobile-first
- Availability engine with the exclusion constraint
- Walk-in entry, staff day view
- M-Pesa deposit + idempotent callback handling
- SMS/WhatsApp confirmation + reminders (two, both conditional — see §6, which this line originally contradicted)
- Owner dashboard: today's bookings, no-show rate, revenue per staff
- Embeddable widget + public API for `/site`
- Single client-initiated reschedule: moving one booking to another time, from the SMS manage link

**Explicitly out — do not build these without being asked:**
Clinics, inventory, POS, payroll/commission, loyalty points, multi-currency, native mobile app, multi-party rescheduling cascades, Google Calendar sync.

Rescheduling needs the distinction spelled out, because the earlier wording was too broad. **A single client moving their own booking to another free slot is in scope** — it is one write against the availability engine, and the design makes it the primary action on both cancel screens because moving beats cancelling for everyone. What stays out is the *cascade*: shifting a booking that displaces another, negotiating between two clients, or rippling a staff schedule change across a day's appointments. One booking, one move, no knock-on.

Two bounds added when slice 7 built it:

- **Three moves per booking** (`lifecycle.MAX_RESCHEDULES`). Each move invalidates a stylist's planning for a day. A refusal still offers cancel, so nobody is trapped.
- **Moving never restores refundability.** `entered_refund_window_at` is a one-way latch, stamped the first time a booking is seen inside its shop's refund window and never cleared. Without it the reschedule button is a refund button: sit inside the window where a cancel yields credit, move six weeks out, cancel for cash. Moving *into* the window is allowed and stamps immediately — a client taking a slot three hours away has knowingly taken a tight one. Same service, same stylist; a stylist change only ever falls out of "anyone available".

Clinics are out on purpose: appointment records tied to a medical practice edge into health data under the Kenya Data Protection Act 2019, which is a materially higher compliance burden. Clinics are a later phase with legal review, not a label change.

---

## 9. Compliance baseline

Client names, phone numbers and visit history are personal data under the Kenya DPA 2019. BookNasi is a controller for its own users and a processor for its shops' clients. Any feature touching client data must keep these working: stated retention period, export path, delete path, processor clause honoured. Deleting a client must not orphan appointment records in a way that breaks reporting — soft-delete with PII scrub, not a cascade.

---

## 10. Design invariants — not themeable, not negotiable

The design handoff isolates four things that survive any re-skin. They are not styling choices; they are the difference between a payment that completes and one that doesn't. A host embedding the widget can override accent, surface, canvas, border, radius, fonts and label casing — and can relabel "deposit" itself, since money words are copy tokens. It cannot touch these:

1. **52 px minimum target height** on any interactive control. Staff use this standing, one-handed, with wet hands; clients use it on a phone on 3G. Walk-in rows go further, to 64–72 px.
2. **Three-per-row slot grid.** Denser grids raise mis-taps on exactly the screen where a mis-tap books the wrong time. Wider ones push afternoon slots below the fold.
3. **The hold countdown stays visible.** It is the only reason it is safe to ask a client to leave the page and open their M-Pesa PIN prompt. Hiding it turns a 3-minute hold into an unexplained failure.
4. **The `*334#` USSD fallback line** on the STK waiting screen. When the push doesn't arrive — and it often doesn't — this is the difference between a completed deposit and an abandoned booking.

These ship as constants in `packages/tokens`, never as CSS custom properties, so a host stylesheet physically cannot override them. The refund/forfeit sentence may be translated or relabelled but never removed.

---

## 11. Working conventions

- **One slice at a time.** Foundation → org/shop/staff/service → availability engine → booking flow → payments → notifications → dashboard → widget. Each slice reviewed and committed before the next starts.
- Write the test with the code. Availability and payment callbacks need concurrency tests, not just happy-path ones.
- Migrations are reviewed by hand. The exclusion constraint and unique constraints go in migrations, never in a manual SQL step someone has to remember.
- Don't add a dependency to solve something the stdlib or Django already does.
- Ask before changing the data model shape in §3 or removing a constraint in §4/§5. Those are decisions, not implementation details.
- Secrets come from the environment. Nothing real in `.env.example`.

## 12. Decisions on record

Settled 1 August 2026 at the close of design scoping. Implement these; don't re-litigate them. Two questions are still genuinely open and are listed at the bottom.

**Identity**

- **No client account and no OTP.** The client types a phone number at checkout; the STK push to that number is the verification. Booking management happens through an expiring, single-appointment token delivered by SMS — the link is the session.

  Slice 7 built it as a **stored 128-bit random token**, not the signed payload this line originally said. A signed payload is ~120 URL characters and tips most confirmations into a second SMS segment, and §6 calls messaging cost a real line item — a permanent per-message tax to avoid one indexed column is the wrong trade. Random and signed are equally unforgeable; the stored one is additionally *revocable*, which cancelling needs. Lifetime is anchored to `starts_at + 2h` rather than fixed, so a booking six weeks out has a link that lives six weeks. It survives a reschedule on purpose: the move updates the same row, and breaking the link on the action the client just took would strand them behind a second SMS. See `scheduling/manage_tokens.py`. An account requirement or an OTP step costs bookings at exactly the point where they are most likely to drop. The consequence is the deposit-free rule in §5: without a payment there is no verification, so a deposit-free service cannot be booked publicly.
- **Per-person staff logins.** `Staff` is a bookable shop-level row linked to a `Membership`. Staff see only their own day. Shared logins would destroy per-staff revenue attribution, which is the owner dashboard's whole argument. A shared shop-device account is a plausible later addition — leave room for it, build nothing for it now.
- **AuthGate is deferred.** Custom `User` on Django's own auth, phone as `USERNAME_FIELD` (staff invites arrive by SMS and salon staff often have no working email). No new auth dependency. Migrating to AuthGate later is a data move, not a redesign.

**Money**

- **The shop sets the deposit rule**, in three modes: flat KES, percentage of price, or none. Service creation **pre-fills 25%**. Us setting it centrally is a pricing decision inside someone else's business that we can't defend per-shop; leaving it blank means it stays blank.
- **`refund_window_hours` ships in slice 2** with a default of 24.
- **The refund and forfeit terms**, settled 14 August 2026. Four outcomes:

  | What happens | The deposit |
  |---|---|
  | Client cancels more than `refund_window_hours` (default 24) before | Refunded |
  | Client cancels later than that | Becomes credit at that shop, valid `deposit_credit_days` (default 60), against any service |
  | Client does not turn up | Forfeited |
  | The shop cancels | Refunded, regardless of when |

  Late cancellation becomes credit rather than a forfeit because a forfeit gives a client who is already going to miss the appointment a reason to say nothing — and a slot nobody frees is worth less to the shop than a slot freed late. Credit keeps the money in the shop and gets the chair back. The no-show is the only forfeit, and it is the one case the client fully controls.

  The last two rows are **not** shop-configurable, and only the first two have fields. A shop that could keep a deposit against its own cancellation is a term no client would accept if they read it, and they must read it: **the sentence appears on the confirm screen before payment, and again on the booking page the confirmation SMS links to.** `packages/booking-core/src/money.refundSentence` is the one place it is worded; §10 lets a host translate or relabel it, never remove it.

**Delivery**

- **SMS first**, behind the provider interface, sender ID `BOOKNASI`. WhatsApp is a swap, not a rewrite.
- **Subscription state is a plain enum.** No fair-use ceiling modelled, no limit enforcement, until there is a billing slice that needs it.
- **Standalone-first.** The design's client flow assumes a shop-branded page; the widget is a second build target over the same `booking-core`, so shipping standalone first costs the `/site` path nothing.

**Reporting** — settled at slice 9, when the dashboard was built and the design's Overview turned out to ask for one number nobody can produce.

- **There is no "before deposits" baseline, and the dashboard never invents one.** The design draws no-shows before vs after deposits as two bars, 18.4 % grey against 7.1 % green. The "before" is the shop's notebook and we were not there; the first row we can measure was written on the day they signed up. Three ways to fake it were considered and each is worse than not drawing the card: asking the owner for their old rate puts a remembered number on screen indistinguishable from a measured one, for the life of the account; comparing deposit-backed against deposit-free bookings is structurally rigged, because a walk-in is recorded with the client already in the chair and can essentially never be a no-show; shipping the design's numbers as placeholders is not an option. What ships is **the shop against its own preceding period of equal length**, with both date ranges printed so it cannot be read as anything else — plus the forfeited total, which is §1's argument in one number and needs no baseline at all.

- **Revenue is billed, not banked.** `revenue_kes` is `price_snapshot` on completed work — what the shop charged. `money.collected_kes` beside it is the deposit that actually arrived by M-Pesa. Two columns, never summed: balance collection at the chair is out of v1, so the product cannot know the rest was paid and must not imply it. Deposit money is attributed to the **booking**, not to the day it arrived, so every figure on the screen describes the same set of appointments.

- **Unfinished bookings are published, not absorbed.** An appointment whose time has passed while still `confirmed` is one nobody pressed Finish on, and it is missing from revenue, utilisation and the no-show rate alike. A shop where a third of the period is unresolved is being shown numbers that are wrong by a third, so the count appears on the screen next to them. This is a completeness caveat on figures being displayed, and deliberately not the adoption warning ruled out below.

- **The repeat-client rate travels with its coverage.** Walk-ins carry no client record — asking for a name at the chair is friction §4 forbids — so the rate is computed over identified clients and the screen prints what share of the period that was. Without it, a number about a minority of a shop's trade reads as a number about the shop.

- **Owner and manager only.** §12's per-person logins exist so revenue can be attributed per stylist; a stylist who can read the attribution can read everybody's pay. The staff day view is unchanged and there is no query parameter that widens it.

- **The headline states a conclusion, and the conclusion is chosen server-side.** The design is right that an owner should not have to do arithmetic to know whether to renew, and "Deposits are working" is also the most dangerous string in the product — it is software making a claim about somebody's business. So `reporting/metrics.verdict_for` picks it where it can be tested against numbers and the client only words it. One ordering rule is load-bearing: **"you are not taking deposits" is reached before anything encouraging**, because a shop with every service set to no-deposit is the shop that churns and is the one that most easily looks fine on a quiet fortnight.

**The widget** — settled at slice 10, when the second front door was built.

- **A renderer, not a second implementation, and it is now proven.** `packages/widget` draws the same eight screens over the same `booking-core`: `stepFor` picks the screen, `offeredSlots` the slots, `canContinue` and `blockedReason` the button and its refusal, `countdownLabel` the timer's words. There is no `if (payment.state === …)` in the widget and `check-widget.mjs` refuses one. This is what slice 5's framework-free package was for, and the answer turned out to be yes.

- **No framework in the bundle.** 12 kB gzipped, everything included, against roughly 45 kB for React before a screen exists — for eight screens of buttons, on 3G, where the design's measure is sixty seconds from a WhatsApp link to a paid deposit. A host may also already run React at another version. So the widget ships sixty lines of virtual node and a fifty-line reconciler, and the build fails past a **20 kB gzipped budget**, which is what makes adding a date library an argument somebody has to have.

- **A shadow root, because §10's invariants have to survive a stranger's stylesheet.** A host rule saying `#booking button { height: 36px }` is not malice, it is a designer being consistent, and it lands on the screen where a mis-tap books the wrong time. Selectors do not cross a shadow boundary; custom properties do. The boundary is therefore a **valve — selectors out, named values in** — which is the shape §10 already described. An iframe would block the values too and leave nothing themeable; a plain `div` blocks nothing. `.bn-root` inside the root redefines every token, so host overrides arrive only through the named option list and never by inheritance.

- **The 52 px floor ships in pixels, never `rem`.** `rem` is a multiple of the *host page's* root font size, so a site running `html { font-size: 12px }` would shrink every target to 39 px with the invariant still correct in the token file and still wrong under the client's thumb. The check reads the **resolved** stylesheet, which `build.mjs` writes out by evaluating the module, because `min-height: ${INVARIANTS.minTargetHeightPx}px` proves only that the constant was mentioned.

- **Text colour is not host-overridable, and that is the deliberate part.** Surfaces, accent, border, radius, fonts and label casing are; ink is not, which is why a dark host site gets a light widget panel — and which is what the design's own neutral-widget mock shows. A host who can set ink can set it to the surface colour, and the refund and forfeit sentence §10 says may be translated or relabelled **but never removed** becomes removable, invisibly, with one hex value and complete deniability. Contrast is the last thing standing between "the terms are on the screen" and "the terms are on the screen in white on white".

- **CORS is `*` on `/api/public/` and nothing anywhere else.** An allowlist of host domains reads safer and protects nothing: the endpoints are unauthenticated, take no cookie, and return what a shop prints on a poster — anything readable through a browser is readable with one line of `curl`, where CORS does not exist. What it *would* do is turn every domain change into a dead booking widget on a Saturday morning. Two rules are not negotiable and are asserted as absences, because a header nobody set leaves no trace in a review: **credentials are never allowed and the origin is never reflected.** The org-scoped `/api/v1/` gets no header at all — the same-origin policy is a control there, not an obstacle. Written in `core/cors.py` rather than installed, because the packaged answer's whole value is configurability and the levers are the hazard.

- **A public 404 stopped being ORM-speak.** `get_object_or_404` writes "No Shop matches the given query.", DRF carries it into `detail`, and the flow puts `detail` on the screen. That sentence was always wrong for a client; the widget made it appear inside a salon's own website, naming a database model, to somebody who arrived from a WhatsApp link. Every 404 under `/api/public/` is now one sentence, and deliberately vague about *which* thing was missing — `lifecycle_views` returns the same 404 for a malformed token and a wrong one so the endpoint is not an existence oracle, and a message that told them apart would hand back what the status code withholds. `/api/v1/` is unchanged: those 404s are read by staff, owners and us.

- **The bundle is built, not committed.** Unlike `packages/tokens/dist`, a minified file is not a reviewable artefact; CI builds it before it checks it and the deploy builds it before it serves it.

**Scope corrections made at the same time**

- Reschedule is **in**, as a single move on a single booking — see §8.
- The staff offline write queue is **out** of the staff-view slice. Optimistic render, retry, and a stale-read banner only. The full queue is tracked, not scheduled.
- Balance collection at the shop and a cash payment type are **out of v1 entirely**. Do not build the affordances the design draws for them.
- **"Anyone available" is earliest-available-slot**, not an assignment algorithm.
- Owner adoption warnings ("Thika Rd has recorded no walk-ins in 9 days") are **out of v1**.

### Settled since

Both of the questions that were open here have been answered. Kept visible rather than deleted, because the reasoning is what stops them being reopened by accident.

1. **Refund and forfeit terms** — decided 14 August 2026, in **Money** above.
2. **The `slotLost` remedy** — decided at slice 6. Screen 8 says the shop calls within the hour and shows the support code that call is about. It deliberately does **not** repeat the design's "automatic refund within 24 hr": nothing automatic exists, the money is with the shop rather than with us, and a promise the product cannot keep is the worst thing to put on the one screen where the client is already unhappy. Slice 7 replaces the phone call with "pick another time and carry your deposit" — `Payment.appointment` is reassignable and `PaymentMove` exists for it. The support code stays either way, and a test asserts the screen never claims an automatic refund.

**Shop setup** — settled at slice 12, when the screen that creates a shop was finally built.

- **"Is this shop bookable yet" is derived on the server**, in `shops/readiness.py`, and the screen only words the answer. Same split as the dashboard's verdict and for a stronger reason: the rule is the availability engine's own composition rule, which §4 allows exactly one implementation of. The parts that catch people out are the parts a TypeScript restatement would get wrong — a missing `StaffService` row means *does not offer this* rather than "offers it with the default duration"; a deposit-free service is not publicly bookable; a stylist rostered only on a day the shop is shut is fully configured and produces nothing; and a shift shorter than the service does not fit it. The last one reads through `resolve_duration`, so a senior stylist's override is honoured.

  It is not a gate — nothing blocks a write, and a shop failing every check still records walk-ins. And it is deliberately not the adoption warning ruled out above: that was unprompted advice about how somebody runs their business, this is a factual answer about whether a feature the owner is actively switching on is switched on yet, asked for by the screen that switches it.

- **A checklist, not a wizard.** The design draws onboarding as four ordered steps and settings as a sidebar; those are the same information twice. The ordering is the valuable half and the one-way door is not — a shop that adds a stylist in March needs the same list to say the new person is rostered with nothing ticked. Slice 11's rule holds: onboarding is somewhere an owner is *sent* by an empty dashboard, which `/owner` now does, and never a landing destination.

- **The deposit pre-fill follows §12, not the design.** The handoff says the deposit editor defaults to flat KES with **nothing pre-filled**; a new service here starts at 25 %. The handoff's own prose advice ("about a quarter of the price") is kept, but it is no longer the only thing between a shop and a deposit-free catalogue.

- **The refund sentence is previewed through `refundSentence`, never restated.** The design asks the settings screen to show "the exact sentence the client will read", and that is only worth anything if it is the same function — a second copy is how a shop shows clients one policy and its owner another. `deposit_credit_days` was added to `ShopSerializer` for it: the field has always been on the model and on the public serializer, and without it the preview would have been half-guessed.

- **No 18 px checkbox anywhere.** The first version put native checkboxes inside 52 px labels, which is the standard accessible pattern and gives a genuinely 52 px hit area. `check-invariants.mjs` refused it and was right to: §10's floor is about a stylist aiming one-handed with wet hands, and an 18 px box is aimed at like an 18 px box whatever its hit area measures. The toggles are `button` + `aria-pressed` with a drawn, `aria-hidden` tick.

### Still open — do not silently decide these

1. **Per-shop M-Pesa credentials.** The design's onboarding step 3 is "connect M-Pesa Paybill/Till", and it is the one step of the four that slice 12 could not build: `MPESA_SHORTCODE` and `MPESA_PASSKEY` are environment-level (`config/settings`), so every shop on the deployment collects into the same till. That is fine for a single-tenant pilot and wrong for the SaaS front door in §1 — a salon's deposits must land in the salon's account.

   Fixing it is a §3 data-model change and a §5 payments change together, so it is not an implementation detail: shortcode, passkey and transaction type would move onto `Shop` (encrypted at rest — they are credentials, and §11 says secrets come from the environment, which this would partly reverse), `payments/stk.py` would resolve them per booking instead of per process, and the callback would have to tolerate more than one shortcode. The alternative is a platform-collects-and-remits model, which is a different business and a licensing question rather than a technical one.

   Do not pick one in a commit. `/setup` currently covers the design's steps 1, 2 and 4 and says nothing about M-Pesa anywhere; that silence is the honest state until this is answered, and is better than a screen implying a connection the deployment does not have.
