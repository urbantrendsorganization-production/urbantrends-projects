from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsSellerOrReadOnly(BasePermission):
    """Anyone may read a listing; only its seller may modify or delete it."""

    message = "You can only modify your own listings."
    code = "not_owner"

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and obj.seller_id == request.user.id)
