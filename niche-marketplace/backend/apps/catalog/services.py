"""Catalog business logic. Views and serializers stay thin and call in here.

Two things are enforced in exactly one place, on purpose:

* **Listing status transitions** — the ``TRANSITIONS`` table below is the single
  source of truth for what state changes are legal. Nothing else flips
  ``Listing.status``.
* **Category-specific attributes** — ``validate_attributes`` checks a listing's
  free-form ``attributes`` against the effective schema of its category.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.exceptions import APIException, ValidationError

from apps.catalog.models import (
    Category,
    Listing,
    ListingImage,
    ListingStatus,
)

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def validate_category_depth(category: Category) -> None:
    """Reject categories deeper than ``Category.MAX_DEPTH`` levels."""
    if category.depth > Category.MAX_DEPTH:
        raise DjangoValidationError(
            f"Categories may be at most {Category.MAX_DEPTH} levels deep."
        )


# ---------------------------------------------------------------------------
# Attribute validation
# ---------------------------------------------------------------------------

_ALLOWED_TYPES = {"string", "number", "boolean", "enum"}


def _coerce_value(field: dict, value):
    """Validate/normalise a single attribute value against its field def.

    Returns the cleaned value or raises ``ValueError`` with a human message.
    """
    ftype = field["type"]

    if ftype == "string":
        if not isinstance(value, str):
            raise ValueError("Must be text.")
        return value.strip()

    if ftype == "number":
        if isinstance(value, bool):  # bool is a subclass of int — reject it
            raise ValueError("Must be a number.")
        if isinstance(value, int | float):
            return value
        try:
            return int(value) if str(value).isdigit() else float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Must be a number.") from exc

    if ftype == "boolean":
        if isinstance(value, bool):
            return value
        if value in ("true", "false"):
            return value == "true"
        raise ValueError("Must be true or false.")

    if ftype == "enum":
        options = field.get("options", [])
        if value not in options:
            raise ValueError(f"Must be one of: {', '.join(map(str, options))}.")
        return value

    # Schema authoring error, not user input — surface loudly.
    raise ValueError(f"Unknown attribute type '{ftype}'.")


def validate_attributes(category: Category, attributes: dict) -> dict:
    """Validate ``attributes`` against ``category``'s effective schema.

    Rejects unknown keys, missing required fields, and type mismatches with a
    per-field error map. Returns the cleaned attribute dict (empty values
    dropped, values coerced to their declared type).
    """
    if not isinstance(attributes, dict):
        raise ValidationError({"attributes": ["Expected an object of attributes."]})

    schema = category.effective_schema()
    defined = {field["key"]: field for field in schema}

    errors: dict[str, str] = {}
    cleaned: dict = {}

    # Unknown keys — a field not defined for this category.
    for key in attributes:
        if key not in defined:
            errors[key] = "Not a valid attribute for this category."

    for key, field in defined.items():
        raw = attributes.get(key)
        missing = key not in attributes or raw in (None, "")
        if missing:
            if field.get("required", False):
                errors[key] = "This attribute is required."
            continue
        try:
            cleaned[key] = _coerce_value(field, raw)
        except ValueError as exc:
            errors[key] = str(exc)

    if errors:
        raise ValidationError({"attributes": errors})
    return cleaned


# ---------------------------------------------------------------------------
# Listing status machine
# ---------------------------------------------------------------------------


class ListingStateError(APIException):
    """A requested status change isn't allowed from the current state."""

    status_code = http_status.HTTP_409_CONFLICT
    default_detail = "That status change isn't allowed."
    default_code = "invalid_transition"


# The only legal status transitions. Everything not listed is forbidden.
#   draft    -> active                     (publish)
#   active   -> reserved / sold / expired  (offer accepted / sold / auto-expiry)
#   reserved -> active / sold              (offer fell through / completed)
#   expired  -> active                     (renew)
#   sold is terminal.
TRANSITIONS: dict[str, set[str]] = {
    ListingStatus.DRAFT: {ListingStatus.ACTIVE},
    ListingStatus.ACTIVE: {
        ListingStatus.RESERVED,
        ListingStatus.SOLD,
        ListingStatus.EXPIRED,
    },
    ListingStatus.RESERVED: {ListingStatus.ACTIVE, ListingStatus.SOLD},
    ListingStatus.EXPIRED: {ListingStatus.ACTIVE},
    ListingStatus.SOLD: set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def transition_listing(listing: Listing, target: str) -> Listing:
    """Move ``listing`` to ``target`` status, enforcing the transition table.

    The single choke point for status changes. Stamps ``published_at`` the first
    time a listing becomes active.
    """
    if target not in ListingStatus.values:
        raise ValidationError({"status": [f"'{target}' is not a valid status."]})

    if listing.status == target:
        return listing  # idempotent no-op

    if not can_transition(listing.status, target):
        raise ListingStateError(
            f"Cannot change a listing from '{listing.status}' to '{target}'."
        )

    listing.status = target
    update_fields = ["status", "updated_at"]

    if target == ListingStatus.ACTIVE and listing.published_at is None:
        listing.published_at = timezone.now()
        update_fields.append("published_at")

    listing.save(update_fields=update_fields)
    return listing


# ---------------------------------------------------------------------------
# Listing CRUD
# ---------------------------------------------------------------------------


@transaction.atomic
def create_listing(
    *, seller, category: Category, attributes: dict | None = None, **fields
) -> Listing:
    """Create a draft listing with validated category attributes."""
    cleaned = validate_attributes(category, attributes or {})
    return Listing.objects.create(
        seller=seller,
        category=category,
        attributes=cleaned,
        **fields,
    )


@transaction.atomic
def update_listing(listing: Listing, *, category: Category | None = None,
                   attributes: dict | None = None, **fields) -> Listing:
    """Update editable fields on a listing. Status changes go through
    ``transition_listing`` instead — this never touches status.

    Re-validates attributes whenever either the attributes or the category
    change, so a category switch can't leave stale/invalid attributes behind.
    """
    target_category = category or listing.category

    if category is not None:
        listing.category = category
    if attributes is not None or category is not None:
        source = attributes if attributes is not None else listing.attributes
        listing.attributes = validate_attributes(target_category, source)

    for name, value in fields.items():
        setattr(listing, name, value)

    listing.save()
    return listing


def soft_delete_listing(listing: Listing) -> None:
    """User-facing delete: hide the listing but keep the row."""
    listing.is_deleted = True
    listing.deleted_at = timezone.now()
    listing.save(update_fields=["is_deleted", "deleted_at", "updated_at"])


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def add_image(listing: Listing, image_file, *, order: int | None = None) -> ListingImage:
    """Attach an image to a listing and queue thumbnail generation."""
    if order is None:
        last = listing.images.order_by("-order").first()
        order = (last.order + 1) if last else 0

    image = ListingImage.objects.create(listing=listing, image=image_file, order=order)

    # Imported here to avoid a circular import at module load (tasks imports models).
    from apps.catalog.tasks import generate_thumbnail

    generate_thumbnail.delay(image.pk)
    return image
