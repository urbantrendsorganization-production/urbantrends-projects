# OnboardKit — Pilot Proposal

**Prepared by:** UrbanTrends (urbantrends.dev)
**For:** [Prospective Agency / MFI]
**Date:** [DATE]

> This is a markdown source. PDF conversion is a follow-up step (no PDF toolchain in this repo).

---

## The problem

Client onboarding and KYC at most Kenyan MFIs and insurance agencies is still run on paper. Field officers fill physical forms, photocopy National IDs and KRA PIN certificates, collect signatures, and carry files back to a branch for manual review. The result: lost and illegible documents, slow turnaround, weak audit trails, no reliable way to confirm the client's own phone number, and no clean data to hand to a core system. It doesn't scale, and it doesn't stand up to a compliance review.

## What OnboardKit does

OnboardKit is a client onboarding and KYC portal built for that exact workflow:

- **Field agents** onboard clients on an Android mobile app: client details → KYC document capture (ID front/back, selfie, proof of address) → one-time-code verification of the **client's own phone** → digital consent → submit.
- **Reviewers** work a desktop queue in a browser: they see form data side-by-side with the captured documents and approve, reject with a reason, or return for correction.
- **Admins** manage branches, users, and products, and pull reports and exports.
- Every status change is written to an **append-only event log**, giving each client a complete, tamper-evident onboarding history.

On approval, the client is assigned a permanent client number and an approval SMS is sent (e.g. Africa's Talking, with fallback).

## In scope for the pilot

- One seeded tenant, up to three branches (e.g. Kilimani, Thika, Nakuru), with agent / reviewer / admin roles.
- Full onboarding loop: mobile capture → OTP → consent → submit → desktop review → approve / reject / return.
- KYC document capture and secure storage (ID front, ID back, selfie, proof of address).
- Client phone OTP verification (E.164 +254), digital consent capture, National ID and KRA PIN fields.
- Reviewer queue, application detail with document viewer, and review actions.
- Admin CRUD (branches, users, products), reports (onboardings per agent/branch/period, time-to-approval, rejection reasons), and **CSV/Excel export** of approved clients.
- Approval / rejection SMS notifications.
- Signed demo APK for the agent app.

## Explicitly out of scope for the pilot

To keep the pilot fixed-price and on-time, the following are **not** included (they are candidate Phase-2 items — see pricing):

- **No integration with any core banking or insurance system.** Data leaves OnboardKit as **CSV/Excel export only**.
- **No offline mode** in the agent app (requires a live connection during onboarding).
- **No automated ID verification** against IPRS or any e-KYC provider — **review is manual and human**.
- **No biometrics beyond a selfie photo.**
- **Single-tenant runtime.** One institution per deployment (the schema is tenant-aware for the future, but tenant switching, tenant signup, and multi-tenant behaviour are not enabled).

## Acceptance criteria

The pilot is accepted when, against the seeded pilot tenant:

1. A field agent can complete the full onboarding loop on the Android app — client details, all four KYC documents, client-phone OTP verification, consent, and submit — without losing progress on a dropped connection.
2. A reviewer can see the submitted application in the desktop queue, view the captured documents, and approve, reject-with-reason, or return-for-correction.
3. On approval, the client is assigned a client number and an approval SMS is issued.
4. Every status change appears in the append-only audit trail with actor, from-status, to-status, and reason where applicable.
5. An admin can manage branches/users/products, view the reports, and export approved clients to CSV/Excel.
6. The demo APK installs and runs on a supplied Android device.

## Pricing frame

Fixed-price pilot, structured as:

- **Fixed pilot fee** — one-time, covers delivery of everything in scope above: **[PRICE TBD]**.
- **Optional monthly retainer** — hosting, support, backups, and minor changes after go-live: **[PRICE TBD] / month**.
- **Phase-2 upsells** (quoted separately once the pilot is proven) — e.g. **offline mode** for the agent app, **IPRS / e-KYC integration** for automated ID verification, **core-system integration** beyond CSV/Excel, and multi-branch or multi-tenant expansion: **[PRICE TBD]**.

*(All figures are placeholders. Final pricing is confirmed in the signed statement of work.)*

## Next steps

1. Short scoping call to confirm branches, roles, product list, and export column mapping.
2. Hands-on demo: you drive the live onboarding loop on a phone and leave with this proposal.
3. Countersign the pilot statement of work; UrbanTrends stands up the seeded pilot tenant and schedules delivery.

**Contact:** UrbanTrends — urbantrends.dev
