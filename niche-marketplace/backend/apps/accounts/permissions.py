from rest_framework.permissions import BasePermission


class IsVerified(BasePermission):
    """Allow only authenticated users who have verified their email.

    Phase 1 defines it; Phase 2 applies it to listing creation so unverified
    users cannot post.
    """

    message = "You must verify your email address before doing this."
    code = "email_not_verified"

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_verified)
