# OnboardKit — Live Demo Walkthrough Script

**Target length:** ≤ 2 minutes. Read as timed narration while driving the demo.
**Loop demonstrated:** field agent onboards a client on the phone app → reviewer approves on the desktop office app → approval SMS "lands" (MockProvider in dev).

---

## Before you start (setup, off-camera)

- **Tenant:** Jubilant Microfinance (seeded demo tenant). Branches: **Kilimani**, **Thika**, **Nakuru**.
- **Login credentials** — all seeded users share the password **`Password123!`**:
  - Agent (phone app): `agent.kilimani@jubilant.co.ke`
  - Reviewer (office app): `reviewer.kilimani@jubilant.co.ke`
  - Admin (office app): `admin@jubilant.co.ke`
- Two screens visible: a **phone** running the Flutter agent app, and a **desktop** running the Next.js office app.
- Dev mode: SMS goes through the **MockProvider** — the approval SMS is captured, not sent to a real handset. Have the mock inbox / job row view ready so the message can be shown "landing."

---

## Narration

### [0:00–0:15] — The hook
> "This is OnboardKit — a client onboarding and KYC portal for Kenyan microfinance institutions. Today a field agent enrols a new client entirely on this phone, a reviewer approves it on the desktop, and the client gets an SMS — no paper, in under two minutes."

*(Hold up the phone. It's on the agent app, logged in as `agent.kilimani@jubilant.co.ke`, showing the "My applications" list.)*

### [0:15–0:45] — Agent: client details + KYC documents
> "Our agent starts a new onboarding. First, client details — name, National ID number, KRA PIN, date of birth, phone. Every step saves as we go, so a dropped connection never loses work."

*(Fill/confirm the client detail step, advance the stepper.)*

> "Next, KYC documents — captured with the camera and compressed on-device: ID front, ID back, a selfie, and proof of address."

*(Show the four document tiles moving to an uploaded/processing state.)*

### [0:45–1:10] — Agent: OTP + consent + submit
> "Now we verify it's really the client's phone. OnboardKit sends a one-time code to the **client's** number — six digits, single-use, five-minute expiry — and the agent enters it to confirm."

*(Trigger OTP send, enter the code, show verified.)*

> "The client reviews the terms and gives digital consent. The agent runs the completeness checklist — all four documents, phone verified, consent recorded — and submits."

*(Tick consent, hit Submit. Stepper shows the application as Submitted.)*

### [1:10–1:40] — Reviewer: the queue + approval
> "Over on the desktop, the reviewer for the Kilimani branch sees that application land in the review queue."

*(Switch to desktop, logged in as `reviewer.kilimani@jubilant.co.ke`. Open the new Submitted application.)*

> "They see the form data side-by-side with the actual KYC images, pulled through short-lived secure links. Everything checks out — they start the review and approve."

*(Open the detail view, show documents, click Start review → Approve.)*

> "On approval, OnboardKit assigns the client their permanent client number — here, **JM-000xx** — and queues the approval SMS."

*(Point to the newly assigned client number, e.g. `JM-00041`.)*

### [1:40–2:00] — The SMS lands + close
> "And the approval SMS lands. In this demo we're running the mock SMS provider, so here's the exact message the client would receive on their +254 phone — confirming they're onboarded."

*(Show the captured SMS in the mock inbox / job row.)*

> "That's the whole loop — field capture to approved client to notification. Every status change is recorded in an append-only audit trail, so there's a full compliance history behind each client. Paper KYC, done in two minutes."

---

## Presenter notes

- If asked about the client number format: it's a **tenant-scoped sequence** (`JM-000xx`) assigned only on approval.
- If asked "is the SMS real?": in the demo it's the **MockProvider**; production uses Africa's Talking (primary) with an Infobip fallback, all sent through the background job queue.
- Keep the phone and desktop both visible during the handoff at [1:10] — the cross-device moment is the point of the demo.
- The demo tenant is fully seeded (~40 applications across all statuses), so the queue looks realistic, not empty.
