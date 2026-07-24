"""Seed a large batch of realistic active listings for browse/search demos.

Phase 3's directory only earns its keep against real volume, so this fills the
catalog with a configurable number of listings (default 1000) spread across the
seeded category tree, each with schema-valid attributes, a staggered
publication time, and a populated full-text vector.

    python manage.py seed_listings              # 1000 listings
    python manage.py seed_listings --count 250
    python manage.py seed_listings --fresh      # wipe seeded listings first

Requires the category tree to exist — run ``seed_catalog`` first.
"""
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.catalog import services
from apps.catalog.models import Category, Condition, Listing, ListingStatus

User = get_user_model()

# Demo sellers created (idempotently) to own the listings.
SELLER_NAMES = [
    "Amina Yusuf", "Brian Otieno", "Cynthia Wanjiru", "David Kimani",
    "Esther Njoroge", "Faisal Ahmed", "Grace Mumbi", "Hassan Ali",
    "Irene Chebet", "James Mwangi", "Kevin Odhiambo", "Lydia Akinyi",
]

LOCATIONS = [
    "Nairobi", "Mombasa", "Kisumu", "Nakuru", "Eldoret", "Thika",
    "Nyeri", "Machakos", "Kikuyu", "Ruiru", "Naivasha", "Kitengela",
]

CONDITIONS = [c for c in Condition.values]

# Word banks for plausible titles, keyed by the top-level category name. Falls
# back to GENERIC for anything not listed.
TITLE_WORDS = {
    "Electronics": (
        ["Samsung", "Apple", "Tecno", "Infinix", "HP", "Dell", "Sony", "LG"],
        ["Galaxy A14", "iPhone 12", "Spark 10", "Note 30", "Pavilion 15",
         "Latitude", "Bravia 43\"", "UltraHD TV"],
    ),
    "Vehicles": (
        ["Toyota", "Nissan", "Mazda", "Subaru", "Honda", "Mitsubishi"],
        ["Axio", "Note", "Demio", "Forester", "Fit", "Outlander", "Vitz"],
    ),
    "Home & Furniture": (
        ["Solid", "Modern", "Vintage", "Compact", "Executive"],
        ["3-seater sofa", "coffee table", "6-piece dining set", "wardrobe",
         "office desk", "bookshelf", "bed frame"],
    ),
    "Fashion": (
        ["Nike", "Adidas", "Zara", "Levi's", "Puma", "H&M"],
        ["running shoes", "denim jacket", "hoodie", "sneakers",
         "leather bag", "sundress"],
    ),
    "Property": (
        ["Spacious", "Cozy", "Modern", "Furnished", "Newly built"],
        ["1-bedroom apartment", "bedsitter", "2-bedroom flat", "studio",
         "maisonette", "town house"],
    ),
}
GENERIC = (["Quality", "Affordable", "Barely used"], ["item", "unit", "piece"])

# Price band (KES) by top-level category, keeps prices believable.
PRICE_BANDS = {
    "Electronics": (3_000, 180_000),
    "Vehicles": (350_000, 3_500_000),
    "Home & Furniture": (2_000, 90_000),
    "Fashion": (500, 12_000),
    "Property": (8_000, 250_000),
}
DEFAULT_BAND = (1_000, 50_000)

DESCRIPTIONS = [
    "In great shape, barely used. Serious buyers only.",
    "Well maintained and ready to use. Price slightly negotiable.",
    "Selling because I'm upgrading. Everything works perfectly.",
    "Clean and functional. Can deliver within town at a fee.",
    "Quick sale. First to come with cash carries the day.",
]


class Command(BaseCommand):
    help = "Seed a large batch of realistic active listings for demos."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=1000,
                            help="How many listings to create (default 1000).")
        parser.add_argument("--fresh", action="store_true",
                            help="Delete previously seeded listings first.")
        parser.add_argument("--seed", type=int, default=None,
                            help="RNG seed for reproducible data.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["seed"] is not None:
            random.seed(options["seed"])

        categories = list(Category.objects.all())
        if not categories:
            raise CommandError("No categories found — run `seed_catalog` first.")

        sellers = self._ensure_sellers()

        if options["fresh"]:
            deleted, _ = Listing.objects.filter(seller__in=sellers).delete()
            self.stdout.write(f"Removed {deleted} previously seeded rows.")

        # Only leaf-ish categories (depth 2–3) carry meaningful attributes; use
        # any non-root so listings inherit a schema to fill.
        postable = [c for c in categories if c.parent_id is not None] or categories
        roots = {c.pk: c for c in categories}

        count = options["count"]
        now = timezone.now()
        batch: list[Listing] = []
        for i in range(count):
            category = random.choice(postable)
            top = self._top_level(category, roots).name
            batch.append(self._build_listing(category, top, sellers, now, i))

        Listing.objects.bulk_create(batch, batch_size=500)

        # Stagger created_at/published_at so "newest" ordering looks alive.
        for listing in batch:
            offset = timedelta(minutes=random.randint(0, 60 * 24 * 45))
            listing.created_at = now - offset
            listing.published_at = now - offset
        Listing.objects.bulk_update(
            batch, ["created_at", "published_at"], batch_size=500
        )

        # Populate the FTS index for everything we just made, in one UPDATE.
        services.refresh_search_vector(*[listing.pk for listing in batch])

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(batch)} active listings across "
            f"{len(postable)} categories, owned by {len(sellers)} sellers."
        ))

    # -- helpers -----------------------------------------------------------

    def _ensure_sellers(self) -> list:
        sellers = []
        for idx, name in enumerate(SELLER_NAMES):
            user, _ = User.objects.get_or_create(
                email=f"seller{idx + 1}@demo.marketplace",
                defaults={"display_name": name,
                          "location": random.choice(LOCATIONS),
                          "is_verified": True},
            )
            sellers.append(user)
        return sellers

    def _top_level(self, category: Category, roots: dict) -> Category:
        node = category
        while node.parent_id is not None:
            node = roots[node.parent_id]
        return node

    def _build_listing(self, category, top, sellers, now, i) -> Listing:
        adjectives, nouns = TITLE_WORDS.get(top, GENERIC)
        title = f"{random.choice(adjectives)} {random.choice(nouns)}"
        low, high = PRICE_BANDS.get(top, DEFAULT_BAND)
        price = random.randint(low, high)
        # Round to a marketplace-ish figure.
        price = round(price, -2) if price < 100_000 else round(price, -3)

        return Listing(
            seller=random.choice(sellers),
            category=category,
            title=title,
            description=random.choice(DESCRIPTIONS),
            price=price,
            currency="KES",
            condition=random.choice(CONDITIONS),
            location=random.choice(LOCATIONS),
            status=ListingStatus.ACTIVE,
            attributes=self._make_attributes(category),
        )

    def _make_attributes(self, category: Category) -> dict:
        """Generate schema-valid attribute values for the category."""
        attrs: dict = {}
        for field in category.effective_schema():
            # Fill required fields always; optional ones most of the time.
            if not field.get("required") and random.random() < 0.25:
                continue
            attrs[field["key"]] = self._make_value(field)
        return attrs

    def _make_value(self, field: dict):
        ftype = field["type"]
        if ftype == "enum":
            return random.choice(field.get("options") or ["N/A"])
        if ftype == "boolean":
            return random.choice([True, False])
        if ftype == "number":
            key = field["key"]
            if "year" in key:
                return random.randint(2005, 2024)
            if "mileage" in key:
                return random.randint(20_000, 220_000) // 1000 * 1000
            if "bedroom" in key:
                return random.randint(1, 5)
            if "storage" in key:
                return random.choice([32, 64, 128, 256, 512])
            if "ram" in key:
                return random.choice([4, 8, 16, 32])
            if "screen" in key:
                return random.choice([13, 14, 15, 17])
            return random.randint(1, 64)
        # string: brand/make/material/size — reuse a small pool.
        return random.choice(
            ["Generic", "Assorted", "Standard", "Classic", "Premium"]
        )
