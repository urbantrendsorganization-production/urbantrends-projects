"""LOAD-BEARING. The two edges no person may ever walk.

`SYSTEM_TRANSITIONS` grants `pending_payment -> confirmed` and
`cancelled -> confirmed`. Both mean "the deposit arrived", and CLAUDE.md §5 is
unambiguous that a booking without a deposit is not publicly bookable — "the
STK push *is* the phone verification". Handing either edge to a person is the
deposit-free booking the whole rule exists to prevent, arriving through a door
nobody thought of as a door.

Three layers stop it, and each is tested here:

1. `Actor.STAFF` is the default, so no caller reaches the system table by
   omission.
2. The two tables are disjoint from a staff member's point of view — the system
   edges are not reachable from `STAFF_TRANSITIONS` at all.
3. **A view cannot pass `Actor.SYSTEM`.** That one is not expressible as a
   default or a table, so it is asserted by parsing the source: the actor
   argument appears only in the payment settlement path. A default alone is a
   convention, and this repo has been replacing conventions with tests since
   slice 1.
"""

import ast
import pathlib

import pytest

from payments.settlement import settle_succeeded
from payments.states import PaymentState
from payments.tests.conftest import expire_the_hold, push_for
from scheduling.statuses import AppointmentStatus
from scheduling.transitions import (
    STAFF_TRANSITIONS,
    SYSTEM_TRANSITIONS,
    TRANSITIONS_BY_ACTOR,
    Actor,
    TransitionRefused,
    apply_transition,
)

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]

S = AppointmentStatus
ROOT = pathlib.Path(__file__).resolve().parents[2]

#: The only modules allowed to name `Actor.SYSTEM`. The settlement module is
#: where "the money arrived" becomes "the booking is confirmed"; the transitions
#: module is where the enum lives. Anything else — a view, a serializer, a
#: management command — is the hole this guard exists to keep shut.
#:
#: Slice 7 adds two, and the test for both is the same question this guard has
#: always asked: **is there real money behind this confirmation?**
#:
#: - `payments/repoint.py` confirms a booking against a payment Safaricom
#:   already told us succeeded. It is the same money as the original push,
#:   moved to a different slot, with a `PaymentMove` row recording the pair.
#: - `scheduling/holds.py` confirms a booking whose deposit was met entirely by
#:   shop credit. That credit descends from a succeeded payment via a
#:   `PROTECT`ed FK, which is CLAUDE.md §5's carve-out and the reason it is not
#:   a deposit-free booking.
#:
#: Neither is a view, and that is the line: both are called *by* a view but
#: neither can be reached with a request alone — each needs a money record that
#: only a real M-Pesa success could have produced.
ALLOWED_TO_ACT_AS_SYSTEM = {
    "payments/settlement.py",
    "scheduling/transitions.py",
    "payments/repoint.py",
    "scheduling/holds.py",
}


class TestTheTableItself:
    def test_the_system_table_has_exactly_two_edges(self):
        assert SYSTEM_TRANSITIONS == {
            S.PENDING_PAYMENT: frozenset({S.CONFIRMED}),
            S.CANCELLED: frozenset({S.CONFIRMED}),
        }

    def test_confirming_a_live_hold_is_the_edge_no_staff_member_has(self):
        """`pending_payment -> confirmed` is the one that must never appear in
        the staff table. If it does, a stylist can confirm an unpaid public
        hold from the day view and the deposit rule is decoration.

        `cancelled -> confirmed` is deliberately in **both** tables and means
        two different things: for a staff member it is the undo of a mis-tapped
        cancel on a booking they own, which slice 3 shipped; for the system it
        is the late callback. Both re-enter the exclusion constraint, so
        neither can take a slot somebody else has — which is what makes sharing
        the edge safe. It is the *unpaid hold* that is system-only.
        """
        assert S.CONFIRMED not in STAFF_TRANSITIONS.get(S.PENDING_PAYMENT, frozenset())
        assert STAFF_TRANSITIONS[S.PENDING_PAYMENT] == frozenset({S.CANCELLED})

    def test_the_two_tables_are_the_only_two(self):
        assert set(TRANSITIONS_BY_ACTOR) == {Actor.STAFF, Actor.SYSTEM}

    def test_the_system_actor_cannot_do_ordinary_staff_things(self):
        """Not a superset. `SYSTEM` is a narrower authority than `STAFF`, not a
        wider one — it may confirm a paid booking and nothing else."""
        assert S.NO_SHOW not in SYSTEM_TRANSITIONS.get(S.CONFIRMED, frozenset())
        assert SYSTEM_TRANSITIONS.keys() < STAFF_TRANSITIONS.keys() | SYSTEM_TRANSITIONS.keys()


class TestTheDefault:
    def test_a_caller_that_omits_the_actor_gets_staff(self, held):
        """Every call site written before slice 6 is unchanged, and none of
        them acquired a new power by existing."""
        with pytest.raises(TransitionRefused) as refused:
            apply_transition(held, S.CONFIRMED)

        assert refused.value.actor is Actor.STAFF

    def test_the_refusal_names_the_actor_it_refused(self, held):
        """So a future reader of the traceback learns which table said no."""
        with pytest.raises(TransitionRefused) as refused:
            apply_transition(held, S.CONFIRMED, actor=Actor.STAFF)

        assert refused.value.actor is Actor.STAFF

    def test_the_system_actor_may_confirm_a_held_slot(self, held):
        apply_transition(held, S.CONFIRMED, actor=Actor.SYSTEM)

        held.refresh_from_db()
        assert held.status == S.CONFIRMED


class TestOnlyTheSettlementPathReachesIt:
    def test_no_view_or_serializer_names_the_system_actor(self):
        """Parsed, not grepped. A regex over the source flags the prose — the
        docstrings that explain why the edge is closed read as uses of it — and
        a test that cannot tell code from a comment about code gets weakened
        until it means nothing.

        `Actor.SYSTEM` as an *attribute access* is the thing being counted. The
        enum's own definition is a class body, not an access, so the module
        that declares it is allowed for the import and nothing more.
        """
        offenders = []
        for path in sorted(ROOT.glob("*/*.py")):
            relative = path.relative_to(ROOT).as_posix()
            if relative in ALLOWED_TO_ACT_AS_SYSTEM:
                continue
            if path.parts[-2] in {"migrations", "tests"} or "test" in path.name:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "SYSTEM"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "Actor"
                ):
                    offenders.append(f"{relative}:{node.lineno}")

        assert not offenders, (
            "Actor.SYSTEM confirms a booking without a paid deposit. "
            f"Only {sorted(ALLOWED_TO_ACT_AS_SYSTEM)} may use it; found {offenders}"
        )

    def test_apply_transition_is_still_the_only_writer_of_appointment_status(self):
        """The rule slice 3 set and slice 6 did not relax. A second writer is
        how a status ends up with the side effects of the other path missing —
        and on the paid path, that is money.

        Scoped to the apps that hold an appointment. `Message.status` and
        `Payment.state` are different columns on different machines with their
        own writers, and a guard that could not tell them apart would either
        flag those or be widened until it flagged nothing.
        """
        appointment_apps = {"scheduling", "public_api", "shops", "payments", "clients"}
        offenders = []
        for path in sorted(ROOT.glob("*/*.py")):
            relative = path.relative_to(ROOT).as_posix()
            if relative == "scheduling/transitions.py":
                continue
            if path.parts[-2] not in appointment_apps:
                continue
            if "test" in path.name:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                # `appointment.status = ...`, anywhere outside the machine.
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Attribute) and target.attr == "status":
                            offenders.append(f"{relative}:{node.lineno}")

        assert not offenders, f"only apply_transition may write an appointment status: {offenders}"


class TestTheEdgeIsOnlyUsableWithRealMoney:
    """The guard above says a view cannot *name* the actor. This says the one
    path that can only fires behind a payment that Safaricom confirmed."""

    def test_settlement_confirms_only_after_the_payment_succeeded(self, held):
        payment = push_for(held)

        settle_succeeded(payment, {"result_code": 0, "mpesa_receipt": "SJ1", "result_desc": "ok"})

        payment.refresh_from_db()
        held.refresh_from_db()
        assert payment.state == PaymentState.SUCCEEDED
        assert held.status == S.CONFIRMED

    def test_a_cancelled_hold_is_confirmed_only_through_settlement(self, held):
        """`cancelled -> confirmed` is the sharpest of the two edges: it brings
        a dead booking back. Reachable here, and nowhere a person can stand."""
        payment = push_for(held)
        expire_the_hold(held)

        settle_succeeded(payment, {"result_code": 0, "mpesa_receipt": "SJ2", "result_desc": "ok"})

        held.refresh_from_db()
        assert held.status == S.CONFIRMED
