"""The three messages this slice sends, and the interface they go through.

CLAUDE.md §6: "Keep the provider behind an interface so SMS → WhatsApp Business
API is a swap, not a rewrite." The test that makes that claim true is
`test_the_provider_is_never_handed_a_rendered_sentence` — an interface of
`send(to, text)` is behind an interface and is still a rewrite, because WhatsApp
Business accepts a pre-approved template name and a variable list, not prose.

Messaging cost is a real line item on the same page of CLAUDE.md, which is why
the one-shot constraint is tested at the database rather than trusted to the
callback dedupe above it.
"""

import pytest

from notifications.models import Message, MessageStatus
from notifications.providers import Outgoing
from notifications.service import queue_message, variables_for
from notifications.templates import ONE_SHOT, RENDERERS, Template, render
from payments.tests.conftest import push_for, stk_callback

pytestmark = [pytest.mark.django_db]


#: Delivery happens in `transaction.on_commit`, which never fires under
#: pytest-django's default rollback wrapper — the transaction is discarded, not
#: committed. That is exactly the property being relied on in production (a
#: rolled-back payment leaves no promise to message anybody), so the tests that
#: need a real send ask for a real commit rather than the module reaching around
#: `on_commit` to be testable.
committing = pytest.mark.django_db(transaction=True)


class TestTheProviderContract:
    @committing
    def test_the_provider_is_never_handed_a_rendered_sentence(self, held, monkeypatch):
        """The whole of the WhatsApp claim. If a rendered string ever reaches
        the provider, the next adapter has to parse our own copy back apart —
        and keep doing it every time somebody edits a template."""
        from notifications import providers

        seen = []

        class Recording:
            name = "recording"

            def send(self, message):
                seen.append(message)
                return providers.DeliveryReceipt(provider_message_id="r-1")

        monkeypatch.setattr(providers, "_provider", Recording())
        payment = push_for(held)
        from payments.callbacks import handle_callback

        handle_callback(stk_callback(payment.checkout_request_id))

        assert len(seen) == 1
        outgoing = seen[0]
        assert isinstance(outgoing, Outgoing)
        assert outgoing.template == Template.BOOKING_CONFIRMED
        assert isinstance(outgoing.variables, dict)
        # No rendered text anywhere on the object.
        assert not hasattr(outgoing, "body")
        assert not hasattr(outgoing, "text")

    def test_the_sender_id_is_provider_configuration_not_a_variable(self, held):
        """`BOOKNASI` is an SMS concept. A WhatsApp adapter has a phone number
        id instead, and a caller passing a sender is passing something the next
        provider cannot use."""
        variables = variables_for(held, Template.BOOKING_CONFIRMED)

        assert "sender" not in variables
        assert "BOOKNASI" not in str(variables)

    def test_every_template_renders(self, held):
        """The console provider renders through the same table the SMS adapter
        would, so a template with a missing variable fails here first."""
        payment = push_for(held)
        payment.mpesa_receipt = "SJ42K19XQ7"
        for template in Template:
            variables = variables_for(held, template, payment=payment)
            assert render(template, variables)

    def test_every_template_has_a_renderer(self):
        assert set(RENDERERS) == set(Template)


class TestTheCopyRules:
    """From the design's message templates: time and place in the first clause,
    money as a plain KES figure, exactly one link, no greeting, no sign-off, no
    emoji."""

    def _rendered(self, held, template):
        payment = push_for(held)
        payment.mpesa_receipt = "SJ42K19XQ7"
        return render(template, variables_for(held, template, payment=payment))

    @pytest.mark.parametrize("template", list(Template))
    def test_there_is_no_greeting_or_sign_off(self, held, template):
        body = self._rendered(held, template)

        assert not body.lower().startswith(("hi", "hello", "dear"))
        assert "regards" not in body.lower()

    def test_the_confirmation_leads_with_the_time(self, held):
        body = self._rendered(held, Template.BOOKING_CONFIRMED)

        assert body.startswith("Booked:")
        assert "M-Pesa SJ42K19XQ7" in body

    def test_the_slot_lost_message_carries_the_code_and_the_number(self, held):
        """This slice's remedy for slotLost is the shop phoning the client, so
        the message says so plainly and hands over what the call needs."""
        body = self._rendered(held, Template.SLOT_LOST)

        assert "will call you within the hour" in body
        assert "BK-" in body

    def test_the_slot_lost_message_does_not_promise_an_automatic_refund(self, held):
        """The design's screen 8 said "automatic refund within 24 hr". Nothing
        automatic exists, the money is with the shop, and a promise we cannot
        keep is worse than the phone call we can."""
        body = self._rendered(held, Template.SLOT_LOST)

        assert "refund" not in body.lower()
        assert "24" not in body

    def test_the_hold_released_message_says_nothing_was_taken(self, held):
        body = self._rendered(held, Template.HOLD_RELEASED)

        assert "Nothing was taken" in body


class TestOneShotIsEnforcedAtTheDatabase:
    def test_the_same_message_cannot_be_queued_twice(self, held):
        first = queue_message(held, Template.HOLD_RELEASED)
        second = queue_message(held, Template.HOLD_RELEASED)

        assert first is not None
        assert second is None
        assert Message.objects.unscoped().filter(template=Template.HOLD_RELEASED).count() == 1

    def test_a_duplicate_callback_cannot_double_message_a_client(self, held):
        """The payment dedupe above this already stops it. The constraint is
        here because the client is charged for neither and trusts both."""
        from payments.callbacks import handle_callback

        payment = push_for(held)
        body = stk_callback(payment.checkout_request_id)
        handle_callback(body)
        handle_callback(body)

        assert Message.objects.unscoped().filter(template=Template.BOOKING_CONFIRMED).count() == 1

    def test_the_one_shot_list_is_a_tuple(self):
        """Not a style point. This list is baked into a migration's constraint
        condition, and `str` hashing is randomised per process — a set would
        serialise in a different order on every run and `makemigrations --check`
        would report a phantom change in CI forever."""
        assert isinstance(ONE_SHOT, tuple)


class TestWhatIsNotStored:
    def test_the_rendered_body_is_not_a_column(self):
        """CLAUDE.md §9. The body carries a name, a time and a phone number;
        keeping a copy of every one is a standing DPA liability for something
        the template and the variables can reproduce."""
        columns = {field.name for field in Message._meta.fields}

        assert "body" not in columns
        assert "text" not in columns

    def test_a_walk_in_is_never_messaged(self, shop_setup, wednesday):
        """A walk-in has no client and never will — CLAUDE.md §4. Nothing to
        say and nobody to say it to."""
        from scheduling.booking import create_appointment
        from scheduling.statuses import BookingSource
        from scheduling.tests.conftest import eat

        when = eat(wednesday, 14)
        walk_in = create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.shave,
            starts_at=when,
            source=BookingSource.WALK_IN,
            now=when,
        )

        assert queue_message(walk_in, Template.BOOKING_CONFIRMED) is None


@committing
class TestDelivery:
    def test_a_queued_message_is_sent_by_the_worker(self, held, console_messages):
        message = queue_message(held, Template.HOLD_RELEASED)

        message.refresh_from_db()
        assert message.status == MessageStatus.SENT
        assert message.provider == "console"
        assert message.sent_at is not None

    def test_delivering_twice_is_harmless(self, held):
        """Safe to lose and safe to run twice, like every other task here."""
        from notifications.tasks import deliver_message

        message = queue_message(held, Template.HOLD_RELEASED)

        assert deliver_message(str(message.pk)) == "resolved"

    def test_a_refused_message_is_retried_once_then_left_visible(self, held, monkeypatch):
        """`MAX_ATTEMPTS` is two, and it has to mean two.

        The row used to be loaded with `status=QUEUED` only, and a single
        refusal sets it FAILED — so the second attempt the constant documents
        could never happen and one transient gateway refusal permanently lost a
        booking confirmation. Two attempts, then it sits FAILED for someone to
        see; still not a loop.
        """
        from notifications import providers
        from notifications.tasks import MAX_ATTEMPTS, deliver_message

        class Refusing:
            name = "refusing"

            def send(self, message):
                return providers.DeliveryReceipt(
                    accepted=False, error_code="21610", error_detail="unsubscribed"
                )

        monkeypatch.setattr(providers, "_provider", Refusing())
        message = queue_message(held, Template.HOLD_RELEASED)

        message.refresh_from_db()
        assert message.status == MessageStatus.FAILED
        assert message.error_detail == "unsubscribed"
        assert message.attempts == 1

        # The second attempt is reachable — the whole point of the fix.
        assert deliver_message(str(message.pk)) == MessageStatus.FAILED
        message.refresh_from_db()
        assert message.attempts == MAX_ATTEMPTS

        # And then it stops. Bounded, not a loop.
        assert deliver_message(str(message.pk)) == "exhausted"

    def test_a_sent_message_is_never_redelivered(self, held, console_messages):
        """The retry widened the load to FAILED as well as QUEUED. SENT stays
        excluded, which is what keeps the task safe to run twice."""
        from notifications.tasks import deliver_message

        message = queue_message(held, Template.HOLD_RELEASED)
        message.refresh_from_db()
        assert message.status == MessageStatus.SENT

        assert deliver_message(str(message.pk)) == "resolved"
        message.refresh_from_db()
        assert message.attempts == 1

    def test_the_cost_is_recorded(self, held, console_messages):
        """Messaging cost is a real line item — CLAUDE.md §6 — and a number
        nobody records is a number nobody manages."""
        message = queue_message(held, Template.HOLD_RELEASED)

        message.refresh_from_db()
        assert message.cost_kes is not None
