"""Catalog domain: the category tree and the listings that hang off it.

Business rules (level limits, status transitions, attribute validation) live in
``services.py`` — the models stay declarative. Listings are user-facing, so they
soft-delete; categories and images hard-delete per project convention.
"""
from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Category(TimeStampedModel):
    """A node in the category tree (max 3 levels deep, enforced in services).

    Each category may declare an ``attribute_schema`` — an ordered list of field
    definitions that listings in this category (and its descendants) must fill
    in. Schemas are inherited: a child's effective schema is its ancestors'
    schemas merged with its own (child keys win). See ``effective_schema``.
    """

    MAX_DEPTH = 3

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=140, unique=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE,
    )
    # Ordered list of {key, label, type, required, options?} dicts. Validated
    # against listing.attributes in services.validate_attributes.
    attribute_schema = models.JSONField(default=list, blank=True)
    # Manual ordering within a parent (lower first), then alphabetical.
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "catalog_category"
        ordering = ["order", "name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name

    def ancestors(self) -> list["Category"]:
        """Root-first chain of parents, excluding self. Walks up the FK."""
        chain: list[Category] = []
        node = self.parent
        while node is not None:
            chain.append(node)
            node = node.parent
        chain.reverse()
        return chain

    @property
    def depth(self) -> int:
        """1 for a root category, 2 for its children, etc."""
        return len(self.ancestors()) + 1

    def effective_schema(self) -> list[dict]:
        """This category's own schema merged over its ancestors' schemas.

        Fields are keyed by ``key``; a descendant redefining a key overrides the
        ancestor's version. Order follows ancestors-first, then this node's own
        new fields.
        """
        merged: dict[str, dict] = {}
        for node in [*self.ancestors(), self]:
            for field in node.attribute_schema or []:
                merged[field["key"]] = field
        return list(merged.values())

    def descendant_ids(self) -> list[int]:
        """This category's id plus every descendant id (for subtree filters).

        Bounded by MAX_DEPTH, so a handful of small queries — fine for the
        directory filters added in Phase 3.
        """
        ids = [self.pk]
        frontier = [self.pk]
        while frontier:
            children = list(
                Category.objects.filter(parent_id__in=frontier).values_list(
                    "pk", flat=True
                )
            )
            ids.extend(children)
            frontier = children
        return ids


class Condition(models.TextChoices):
    NEW = "new", "New"
    LIKE_NEW = "like_new", "Like new"
    GOOD = "good", "Good"
    FAIR = "fair", "Fair"
    FOR_PARTS = "for_parts", "For parts / not working"


class ListingStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    RESERVED = "reserved", "Reserved"
    SOLD = "sold", "Sold"
    EXPIRED = "expired", "Expired"


class ListingQuerySet(models.QuerySet):
    def alive(self) -> "ListingQuerySet":
        """Exclude soft-deleted listings."""
        return self.filter(is_deleted=False)

    def active(self) -> "ListingQuerySet":
        """Publicly visible listings (alive + active status)."""
        return self.alive().filter(status=ListingStatus.ACTIVE)

    def with_related(self) -> "ListingQuerySet":
        """Prefetch everything a serialized listing touches — no N+1."""
        return self.select_related("seller", "category").prefetch_related("images")


class Listing(TimeStampedModel):
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="listings",
        on_delete=models.CASCADE,
    )
    # PROTECT: a category with listings can't be deleted out from under them.
    category = models.ForeignKey(
        Category,
        related_name="listings",
        on_delete=models.PROTECT,
    )

    title = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="KES")
    condition = models.CharField(max_length=20, choices=Condition.choices)
    location = models.CharField(max_length=120, blank=True)

    status = models.CharField(
        max_length=12,
        choices=ListingStatus.choices,
        default=ListingStatus.DRAFT,
    )
    # Category-specific values, validated against category.effective_schema().
    attributes = models.JSONField(default=dict, blank=True)

    # Soft delete — listings are user-facing.
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    # Set the first time a listing goes active; used for sorting/expiry later.
    published_at = models.DateTimeField(null=True, blank=True)

    objects = ListingQuerySet.as_manager()

    class Meta:
        db_table = "catalog_listing"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["category", "status"]),
            models.Index(fields=["seller", "-created_at"]),
        ]

    def __str__(self) -> str:
        return self.title


class ListingImage(TimeStampedModel):
    listing = models.ForeignKey(
        Listing,
        related_name="images",
        on_delete=models.CASCADE,
    )
    image = models.ImageField(upload_to="listings/")
    # Generated asynchronously by a Celery task after upload.
    thumbnail = models.ImageField(upload_to="listings/thumbs/", blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "catalog_listing_image"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"Image #{self.pk} for listing {self.listing_id}"
