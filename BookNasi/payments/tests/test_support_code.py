"""LOAD-BEARING. The code the client reads down the phone, and the lookup.

The decision on record: derived from the payment, short, readable down a phone
line, non-guessable — and **searchable in Django admin in this slice**. The
owner dashboard is slice 9, and a code nobody can look up until then is
decoration on the one screen where the client is already unhappy.

Each of those four words is a constraint, and they pull against each other:

- *Short* and *readable* rule out a UUID. Nobody reads 36 characters over a bad
  line in a noisy salon.
- *Non-guessable* rules out a sequence. `BK-40219` — the design's own example —
  tells a stranger roughly how many payments this product has taken and lets
  them walk the neighbours, and the support desk cannot tell a wrong guess from
  a real code.
- Crockford base32 drops I, L, O and U: the first three because they collide
  with 1 and 0 in speech and in handwriting, and U so the alphabet cannot spell
  anything the shop has to apologise for.
"""

import re

import pytest

from payments.models import Payment
from payments.states import PaymentState
from payments.support_codes import ALPHABET, new_support_code
from payments.tests.conftest import push_for, stk_callback

pytestmark = [pytest.mark.django_db, pytest.mark.loadbearing]

PATTERN = re.compile(r"^BK-[0-9A-HJKMNP-TV-Z]{6}$")


class TestTheCodeItself:
    def test_it_is_short_and_prefixed(self):
        code = new_support_code()

        assert PATTERN.match(code), code
        assert len(code) == 9

    def test_the_ambiguous_letters_are_absent(self):
        """I/1, L/1, O/0 are indistinguishable down a phone line, and a support
        desk that has to ask "letter or number?" has already lost the minute."""
        for letter in "ILOU":
            assert letter not in ALPHABET

    def test_it_is_not_a_sequence(self):
        """A sequence leaks volume and lets a stranger walk the neighbours."""
        codes = {new_support_code() for _ in range(200)}

        assert len(codes) == 200

    def test_the_space_is_large_enough_that_guessing_is_pointless(self):
        assert len(ALPHABET) ** 6 > 10**9


class TestEveryPaymentHasOne:
    def test_a_push_mints_one(self, held):
        payment = push_for(held)

        assert PATTERN.match(payment.support_code)

    def test_it_is_unique_at_the_database(self, held):
        from django.db import IntegrityError, transaction

        payment = push_for(held)

        with pytest.raises(IntegrityError), transaction.atomic():
            Payment.objects.unscoped().create(
                appointment=held,
                amount=100,
                phone="+254712345678",
                state=PaymentState.FAILED,
                support_code=payment.support_code,
            )

    def test_it_is_what_goes_on_the_clients_m_pesa_statement(self, held, fake_daraja):
        """The reference Safaricom shows the client is the same string the shop
        searches on, which is the only reason a distressed client can be helped
        by somebody who was not there."""
        payment = push_for(held)

        assert fake_daraja.pushes[0]["reference"] == payment.support_code

    def test_it_survives_onto_the_slot_lost_screen(self, api_client, held):
        """Screen 8's whole content is this code plus a phone number."""
        from django.urls import reverse

        payment = push_for(held)
        url = reverse("public_api:hold-detail", kwargs={"hold_id": held.pk})

        body = api_client.get(url).data

        assert body["payment"]["support_code"] == payment.support_code
        assert body["shop_phone"] == held.shop.phone


class TestTheLookupWorksThisSlice:
    """With a client on the phone. Asserted against the admin's real search
    machinery rather than against a queryset, because the thing being promised
    is that somebody can type it into the box and find the row."""

    @pytest.fixture
    def admin_request(self, make_user):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        from payments.admin import PaymentAdmin

        staff = make_user(full_name="Support", phone="+254712999001")
        staff.is_staff = True
        staff.is_superuser = True
        staff.save(update_fields=["is_staff", "is_superuser"])
        request = RequestFactory().get("/admin/payments/payment/")
        request.user = staff
        return request, PaymentAdmin(Payment, AdminSite())

    def test_searching_the_support_code_finds_the_payment(self, held, admin_request):
        request, model_admin = admin_request
        payment = push_for(held)

        found, _ = model_admin.get_search_results(
            request, model_admin.get_queryset(request), payment.support_code
        )

        assert list(found) == [payment]

    def test_searching_the_mpesa_receipt_finds_it_too(self, held, admin_request):
        """A client who lost the booking screen still has the M-Pesa SMS."""
        from payments.callbacks import handle_callback
        from payments.tests.conftest import RECEIPT

        request, model_admin = admin_request
        payment = push_for(held)
        handle_callback(stk_callback(payment.checkout_request_id))

        found, _ = model_admin.get_search_results(
            request, model_admin.get_queryset(request), RECEIPT
        )

        assert list(found) == [payment]

    def test_the_lookup_is_not_scoped_to_one_tenant(self, held, admin_request):
        """The client rings, the shop searches, and neither of them knows an
        organization id. CLAUDE.md §3 names admin tooling as the exception."""
        request, model_admin = admin_request
        payment = push_for(held)

        assert model_admin.get_queryset(request).filter(pk=payment.pk).exists()

    def test_the_exception_queue_shows_paid_with_no_booking(self, shop_setup, held, admin_request):
        from payments.callbacks import handle_callback
        from payments.states import OrphanReason
        from payments.tests.conftest import expire_the_hold
        from scheduling.booking import create_appointment
        from scheduling.statuses import AppointmentStatus, BookingSource

        request, model_admin = admin_request
        payment = push_for(held)
        expire_the_hold(held)
        create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            starts_at=held.starts_at,
            source=BookingSource.WALK_IN,
            status=AppointmentStatus.CONFIRMED,
            now=held.starts_at,
        )
        handle_callback(stk_callback(payment.checkout_request_id))

        queue = model_admin.get_queryset(request).filter(state=PaymentState.ORPHANED)

        assert list(queue) == [payment]
        assert queue.first().orphan_reason == OrphanReason.SLOT_LOST

    def test_money_records_cannot_be_edited_in_the_admin(self, admin_request):
        """A form that can set `state = succeeded` is a form that can confirm a
        booking nobody paid for."""
        request, model_admin = admin_request

        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_change_permission(request) is False
        assert model_admin.has_delete_permission(request) is False
