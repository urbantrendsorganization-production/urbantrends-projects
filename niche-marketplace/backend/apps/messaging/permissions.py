from rest_framework.permissions import BasePermission


class IsParticipant(BasePermission):
    """Only the buyer or seller on a conversation may view or post to it."""

    message = "You are not part of this conversation."
    code = "not_a_participant"

    def has_object_permission(self, request, view, obj) -> bool:
        return obj.involves(request.user)
