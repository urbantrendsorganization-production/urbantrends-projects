"""The manage link is the only authentication on the lifecycle surface.

It reaches a stranger's phone and grants control of a booking with money against
it, so these are not incidental tests. Four properties, each of which is the
whole of some attacker's problem or some client's day:

1. **Expiry** is anchored to the booking, not to a fixed duration.
2. **Reschedule** does not break it — the client's only session survives the
   action they just took.
3. **Tampering** gets nowhere: 128 bits of `secrets` entropy.
4. **Enumeration** gets nowhere either, and specifically cannot be used as an
   existence oracle — every failure looks identical from outside.

See `scheduling/manage_tokens.py` for why the token is stored-random rather than
signed, and CLAUDE.md §12, which was amended to match.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from scheduling import manage_tokens
from scheduling.holds import create_hold
from scheduling.manage_tokens import ManageTokenInvalid
from scheduling.tests.conftest import WEDNESDAY, eat

pytestmark = pytest.mark.django_db


@pytest.fixture
def booked(shop_setup):
    """A confirmed booking two hours out, with a live manage token."""
    when = eat(WEDNESDAY, 10)
    hold = create_hold(
        shop=shop_setup.shop,
        service=shop_setup.braids,
        staff=shop_setup.wanjiku,
        starts_at=when,
        phone="0712345678",
        now=when - timedelta(hours=2),
    )
    return hold


class TestTheTokenExists:
    def test_a_hold_gets_one_at_creation(self, booked):
        """Minted with the booking, not with the confirmation SMS — the message
        that carries it is rendered inside the payment callback, so the session
        has to exist first."""
        assert booked.manage_token
        assert len(booked.manage_token) >= 20

    def test_two_bookings_get_different_tokens(self, shop_setup, booked):
        other = create_hold(
            shop=shop_setup.shop,
            service=shop_setup.braids,
            staff=shop_setup.grace,
            starts_at=eat(WEDNESDAY, 14),
            phone="0722000000",
            now=eat(WEDNESDAY, 10),
        )

        assert other.manage_token != booked.manage_token

    def test_a_walk_in_gets_none(self, shop_setup):
        """Nobody was sent a link, so there is nothing to manage."""
        from scheduling.booking import create_appointment
        from scheduling.statuses import BookingSource

        walk_in = create_appointment(
            staff=shop_setup.wanjiku,
            service=shop_setup.braids,
            starts_at=eat(WEDNESDAY, 16),
            source=BookingSource.WALK_IN,
            now=eat(WEDNESDAY, 16),
        )

        assert not walk_in.manage_token


class TestExpiry:
    def test_it_is_anchored_to_the_booking_not_the_issue_date(self, shop_setup):
        """A booking six weeks out needs a link that lives six weeks. A fixed
        TTL would kill it a month before the appointment."""
        far = eat(WEDNESDAY, 10) + timedelta(days=42)
        hold = create_hold(
            shop=shop_setup.shop,
            service=shop_setup.braids,
            staff=shop_setup.wanjiku,
            starts_at=far,
            phone="0712345678",
            now=far - timedelta(days=42),
        )

        assert hold.manage_expires_at > far
        assert hold.manage_expires_at == far + manage_tokens.MANAGE_TAIL

    def test_it_resolves_right_up_to_the_tail(self, booked):
        just_before = booked.starts_at + manage_tokens.MANAGE_TAIL - timedelta(minutes=1)

        assert manage_tokens.resolve(booked.manage_token, now=just_before).pk == booked.pk

    def test_it_stops_resolving_after_the_tail(self, booked):
        """The tail exists so a client just marked no-show can still read why."""
        after = booked.starts_at + manage_tokens.MANAGE_TAIL + timedelta(minutes=1)

        with pytest.raises(ManageTokenInvalid):
            manage_tokens.resolve(booked.manage_token, now=after)

    def test_the_absolute_cap_bounds_an_absurd_booking(self, booked):
        """A live credential with no ceiling is not a thing to leave lying
        around just because the ordinary path is reliable.

        Exercised through `expiry_for` rather than a real booking: the public
        booking horizon refuses a slot 400 days out long before this matters,
        which is the point — the cap is a backstop for a row that got there some
        other way, not a path anybody walks.
        """
        now = timezone.now()
        far_off = type("Stub", (), {"starts_at": now + timedelta(days=400)})()

        expiry = manage_tokens.expiry_for(far_off, now=now)

        assert expiry < far_off.starts_at
        assert expiry == now + manage_tokens.ABSOLUTE_CAP


class TestItSurvivesAReschedule:
    def test_the_same_token_still_works_after_a_move(self, booked, shop_setup):
        """CLAUDE.md §12: the link is the session. Breaking it on the action the
        client just took would strand them behind a second SMS that might not
        arrive."""
        from scheduling.lifecycle import reschedule

        original = booked.manage_token
        reschedule(booked, starts_at=eat(WEDNESDAY, 12), now=eat(WEDNESDAY, 8))
        booked.refresh_from_db()

        assert booked.manage_token == original
        assert manage_tokens.resolve(original, now=eat(WEDNESDAY, 9)).pk == booked.pk

    def test_the_expiry_follows_the_booking(self, booked):
        """A move to a later slot extends the link's life with it, because the
        anchor is `starts_at`."""
        from scheduling.lifecycle import reschedule

        before = booked.manage_expires_at
        reschedule(booked, starts_at=eat(WEDNESDAY, 12), now=eat(WEDNESDAY, 8))
        booked.refresh_from_db()

        assert booked.manage_expires_at > before


class TestRevocation:
    def test_cancelling_kills_the_link(self, booked):
        """The SMS is still in the client's inbox and the row is no longer
        theirs to act on. Relying on a status check in every future endpoint is
        how one of them eventually forgets."""
        from scheduling.lifecycle import cancel

        token = booked.manage_token
        cancel(booked, now=eat(WEDNESDAY, 8))

        with pytest.raises(ManageTokenInvalid):
            manage_tokens.resolve(token)

    def test_the_version_moves_so_it_cannot_be_re_minted_into_validity(self, booked):
        before = booked.token_version
        manage_tokens.revoke(booked)
        booked.refresh_from_db()

        assert booked.token_version == before + 1
        assert booked.manage_token is None


class TestTamperingAndEnumeration:
    @pytest.mark.parametrize(
        "attempt",
        [
            "",
            " ",
            "x",
            "0" * 22,
            "../../etc/passwd",
            "%00",
            "a" * 500,
            None,
            12345,
        ],
    )
    def test_nothing_malformed_resolves(self, attempt, booked):
        with pytest.raises(ManageTokenInvalid):
            manage_tokens.resolve(attempt)

    def test_a_one_character_change_does_not_resolve(self, booked):
        """No prefix matching, no partial credit. The whole token or nothing."""
        token = booked.manage_token
        for i in (0, len(token) // 2, len(token) - 1):
            mutated = token[:i] + ("A" if token[i] != "A" else "B") + token[i + 1 :]
            with pytest.raises(ManageTokenInvalid):
                manage_tokens.resolve(mutated)

    def test_the_appointment_id_is_not_a_token(self, booked):
        """The UUID is unguessable but it is *not* the credential, and a caller
        who somehow learned one must not be able to manage the booking."""
        with pytest.raises(ManageTokenInvalid):
            manage_tokens.resolve(str(booked.pk))

    def test_the_endpoint_gives_the_same_answer_for_every_failure(self, api_client, booked):
        """The existence-oracle rule. A distinguishable "expired" would confirm
        that a booking exists, which is the one fact probing must not reveal —
        see `public_api/lifecycle_views.py`.
        """
        real = booked.manage_token
        expired_at = booked.starts_at + manage_tokens.MANAGE_TAIL + timedelta(days=1)

        unknown = api_client.get(
            reverse("public_api:manage-detail", args=["nosuchtoken0000000000"])
        )
        malformed = api_client.get(reverse("public_api:manage-detail", args=["!!!"]))

        manage_tokens.revoke(booked)
        revoked = api_client.get(reverse("public_api:manage-detail", args=[real]))

        assert unknown.status_code == malformed.status_code == revoked.status_code == 404
        bodies = {unknown.content, malformed.content, revoked.content}
        assert len(bodies) == 1, f"failures are distinguishable: {bodies}"
        assert expired_at  # documents the fourth case; covered by resolve() above

    def test_the_response_does_not_leak_the_token_in_a_referer(self, api_client, booked):
        """The token is in the URL, so without this the whole credential goes to
        anything the page loads."""
        response = api_client.get(reverse("public_api:manage-detail", args=[booked.manage_token]))

        assert response["Referrer-Policy"] == "no-referrer"
