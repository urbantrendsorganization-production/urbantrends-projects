"""Encrypting a credential, and the ways that goes wrong quietly.

The failure this file guards against is not "the encryption is weak" — Fernet
is a standard construction and testing AES is not our job. It is the two
failures that look like success:

1. **A secret stored in the clear because configuration was incomplete.** A
   `seal` that returned its input when no key was set would work perfectly in
   development, pass every functional test, and put live till passkeys in a
   column on the day somebody forgot an environment variable.
2. **A secret that cannot be read back after a key rotation.** Encryption
   nobody can reverse is data loss with extra steps, and it would be discovered
   by a shop whose deposits stopped arriving.
"""

import pytest
from cryptography.fernet import Fernet

from core import secrets

pytestmark = pytest.mark.loadbearing


KEY_A = "2026a:" + Fernet.generate_key().decode()
KEY_B = "2026b:" + Fernet.generate_key().decode()


class TestARoundTrip:
    def test_what_goes_in_comes_out(self, settings):
        settings.MPESA_CREDENTIAL_KEYS = [KEY_A]

        ciphertext, key_id = secrets.seal("a-passkey")

        assert secrets.unseal(ciphertext, key_id) == "a-passkey"

    def test_the_ciphertext_does_not_contain_the_plaintext(self, settings):
        """The whole point, asserted rather than assumed.

        A `seal` that base64'd its input would satisfy every other test in this
        file — same bytes out as in, key id recorded, rotation "working" — and
        would be a plain encoding with a ceremonial wrapper.
        """
        settings.MPESA_CREDENTIAL_KEYS = [KEY_A]

        ciphertext, _ = secrets.seal("Fq3xPasskeyValue")

        assert b"Fq3xPasskeyValue" not in ciphertext
        assert b"Fq3xPasskeyValue" not in bytes(ciphertext).hex().encode()

    def test_the_same_value_seals_differently_each_time(self, settings):
        """Fernet carries a random IV. Without one, two shops with the same
        passkey would have identical ciphertext, and a column would leak which
        shops share credentials."""
        settings.MPESA_CREDENTIAL_KEYS = [KEY_A]

        first, _ = secrets.seal("same")
        second, _ = secrets.seal("same")

        assert first != second
        assert secrets.unseal(first) == secrets.unseal(second) == "same"

    def test_the_key_id_is_recorded(self, settings):
        settings.MPESA_CREDENTIAL_KEYS = [KEY_A]

        _, key_id = secrets.seal("x")

        assert key_id == "2026a"


class TestEmptyIsNotASecret:
    def test_nothing_in_nothing_out(self, settings):
        settings.MPESA_CREDENTIAL_KEYS = [KEY_A]

        assert secrets.seal("") == (b"", "")

    def test_and_it_survives_a_deployment_with_no_key_at_all(self, settings):
        """Clearing a credential must work on a deployment that cannot seal.

        Otherwise the one action available to a shop whose keys leaked —
        disconnect — is the action that raises.
        """
        settings.MPESA_CREDENTIAL_KEYS = []

        assert secrets.seal("") == (b"", "")

    def test_unsealing_nothing_is_empty_not_an_error(self, settings):
        settings.MPESA_CREDENTIAL_KEYS = [KEY_A]

        assert secrets.unseal(b"") == ""


class TestWithoutAKeyNothingIsStored:
    def test_seal_refuses_rather_than_storing_plaintext(self, settings):
        """The one that matters.

        A `seal` that fell back to returning its input would be invisible: the
        round trip still works, the shop still takes deposits, and the passkey
        is in the database in the clear until somebody reads the column.
        """
        settings.MPESA_CREDENTIAL_KEYS = []

        with pytest.raises(secrets.SealingUnavailable):
            secrets.seal("a-passkey")

    def test_sealing_is_available_says_so_first(self, settings):
        settings.MPESA_CREDENTIAL_KEYS = []
        assert secrets.sealing_is_available() is False

        settings.MPESA_CREDENTIAL_KEYS = [KEY_A]
        assert secrets.sealing_is_available() is True

    def test_a_malformed_key_is_refused_and_not_echoed(self, settings):
        """The message goes in a log. `cryptography` puts the offending value in
        some of its own messages, and a log line containing a key is the thing
        the key was protecting against."""
        settings.MPESA_CREDENTIAL_KEYS = ["2026a:not-a-real-fernet-key"]

        with pytest.raises(secrets.SealingUnavailable) as exc:
            secrets.seal("x")

        assert "not-a-real-fernet-key" not in str(exc.value)
        assert "2026a" in str(exc.value)

    def test_an_entry_with_no_key_is_refused(self, settings):
        settings.MPESA_CREDENTIAL_KEYS = ["2026a"]

        with pytest.raises(secrets.SealingUnavailable):
            secrets.seal("x")


class TestRotation:
    def test_a_new_key_at_the_front_encrypts_and_the_old_one_still_opens(self, settings):
        """What a rotation actually is: add the new key, do nothing else.

        Without this, rotating means re-encrypting every shop in the same
        deployment step, which is the kind of migration people put off.
        """
        settings.MPESA_CREDENTIAL_KEYS = [KEY_A]
        old, old_id = secrets.seal("first-passkey")

        settings.MPESA_CREDENTIAL_KEYS = [KEY_B, KEY_A]
        new, new_id = secrets.seal("second-passkey")

        assert new_id == "2026b"
        assert secrets.unseal(new, new_id) == "second-passkey"
        assert secrets.unseal(old, old_id) == "first-passkey"

    def test_dropping_the_key_that_sealed_a_row_is_loud(self, settings):
        """Not a blank. A blank reads as "this shop never connected M-Pesa" and
        sends the booking down the not-configured path, which is a quieter and
        more confusing wrong answer than saying the row cannot be read."""
        settings.MPESA_CREDENTIAL_KEYS = [KEY_A]
        sealed, key_id = secrets.seal("orphaned")

        settings.MPESA_CREDENTIAL_KEYS = [KEY_B]

        with pytest.raises(secrets.CannotUnseal) as exc:
            secrets.unseal(sealed, key_id)

        assert "2026a" in str(exc.value)

    def test_the_active_key_is_the_first_one(self, settings):
        settings.MPESA_CREDENTIAL_KEYS = [KEY_B, KEY_A]

        assert secrets.active_key_id() == "2026b"


class TestMasking:
    def test_it_shows_the_tail_and_nothing_else(self):
        assert secrets.mask("abcdefghijklmnop") == "••••••••mnop"

    def test_a_short_value_is_hidden_entirely(self):
        """`keep=4` of a six-character secret is not a hint, it is the secret."""
        assert secrets.mask("abcdef") == "••••••••"
        assert "abc" not in secrets.mask("abcdef")

    def test_nothing_masks_to_nothing(self):
        """An empty mask is how the screen tells "not set" from "set, hidden"."""
        assert secrets.mask("") == ""
