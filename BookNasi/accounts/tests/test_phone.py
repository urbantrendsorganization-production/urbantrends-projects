import pytest

from accounts.phone import InvalidPhoneNumber, normalize_phone


@pytest.mark.parametrize(
    "raw",
    [
        "0712345678",
        "712345678",
        "254712345678",
        "+254712345678",
        "+254 712 345 678",
        "0712 345 678",
        "0712-345-678",
        "(+254) 712 345 678",
    ],
)
def test_every_way_a_kenyan_writes_one_number_resolves_to_one_value(raw):
    """The same stylist will type this four different ways across two devices.
    If they resolve to different rows they get locked out of their own account."""
    assert normalize_phone(raw) == "+254712345678"


def test_the_011x_safaricom_range_is_accepted():
    assert normalize_phone("0110123456") == "+254110123456"


@pytest.mark.parametrize(
    "raw",
    ["", None, "0812345678", "071234567", "07123456789", "+1 555 0100", "not a phone", "0"],
)
def test_rejects_what_is_not_a_kenyan_mobile(raw):
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(raw)


@pytest.mark.django_db
def test_user_is_stored_normalised_whatever_was_typed(make_user):
    user = make_user(phone="0712345678")

    assert user.phone == "+254712345678"


@pytest.mark.django_db
def test_uniqueness_holds_across_input_forms(make_user):
    from django.db import IntegrityError

    make_user(phone="+254712345678")

    with pytest.raises(IntegrityError):
        make_user(phone="0712345678")


@pytest.mark.django_db
def test_email_is_stored_lowercased(make_user):
    user = make_user(email="Owner@Shop.CO.KE")

    assert user.email == "owner@shop.co.ke"


@pytest.mark.django_db
def test_many_users_may_have_no_email(make_user):
    """Most salon staff have no working email. `unique=True` on a blank string
    would let exactly one of them exist, so absence has to be NULL."""
    first = make_user(phone="+254712000101")
    second = make_user(phone="+254712000102")

    assert first.email is None and second.email is None
