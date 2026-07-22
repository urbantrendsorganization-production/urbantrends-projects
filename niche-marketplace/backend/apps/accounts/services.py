"""Account business logic. Views/serializers stay thin and call in here.

Email verification uses Django's signing framework: the token is a signed,
timestamped payload of the user id + email. It needs no DB row, expires via
``max_age``, and is effectively one-time because once ``is_verified`` flips
true a replay is a harmless no-op.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.mail import send_mail

User = get_user_model()

VERIFY_SALT = "apps.accounts.email-verify"


class VerificationError(Exception):
    """Raised when a verification token is invalid or expired."""

    def __init__(self, message: str, code: str = "invalid_token"):
        super().__init__(message)
        self.message = message
        self.code = code


def register_user(*, email: str, password: str, display_name: str = "") -> User:
    """Create an unverified user and send them a verification email."""
    user = User.objects.create_user(
        email=email,
        password=password,
        display_name=display_name,
    )
    send_verification_email(user)
    return user


def _make_token(user: User) -> str:
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=VERIFY_SALT)


def build_verification_link(user: User) -> str:
    token = _make_token(user)
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/verify-email?token={token}"


def send_verification_email(user: User) -> None:
    link = build_verification_link(user)
    send_mail(
        subject="Verify your Marketplace account",
        message=(
            f"Welcome to Marketplace!\n\n"
            f"Confirm your email address by opening this link:\n\n{link}\n\n"
            f"The link expires in 24 hours. If you didn't sign up, ignore this."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


def verify_email(token: str) -> User:
    """Validate a token and mark the user verified. Idempotent on replay."""
    try:
        data = signing.loads(
            token, salt=VERIFY_SALT, max_age=settings.EMAIL_VERIFICATION_TIMEOUT
        )
    except signing.SignatureExpired as exc:
        raise VerificationError(
            "This verification link has expired.", code="token_expired"
        ) from exc
    except signing.BadSignature as exc:
        raise VerificationError(
            "This verification link is invalid.", code="invalid_token"
        ) from exc

    try:
        user = User.objects.get(pk=data["uid"], email=data["email"])
    except User.DoesNotExist as exc:
        raise VerificationError(
            "This verification link is invalid.", code="invalid_token"
        ) from exc

    if not user.is_verified:
        user.is_verified = True
        user.save(update_fields=["is_verified", "updated_at"])
    return user


def resend_verification(email: str) -> None:
    """Re-send the verification email. Silent if the email is unknown or
    already verified — we don't reveal which addresses exist."""
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return
    if user.is_verified:
        return
    send_verification_email(user)
