"""Seed a realistic category tree (with attribute schemas) for the marketplace.

Idempotent: categories are matched by slug, so re-running updates in place
rather than duplicating. Run with ``python manage.py seed_catalog``.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from apps.catalog.models import Category

# A three-level tree. Each entry: (name, attribute_schema, [children]).
# Attribute schemas are declared at the level where they make sense and are
# inherited by descendants (see Category.effective_schema).
TREE = [
    (
        "Electronics",
        [],
        [
            (
                "Phones & Tablets",
                [
                    {"key": "brand", "label": "Brand", "type": "string", "required": True},
                    {"key": "storage_gb", "label": "Storage (GB)", "type": "number"},
                ],
                [
                    (
                        "Mobile Phones",
                        [
                            {
                                "key": "network",
                                "label": "Network",
                                "type": "enum",
                                "options": ["Unlocked", "Safaricom", "Airtel", "Telkom"],
                            },
                            {"key": "dual_sim", "label": "Dual SIM", "type": "boolean"},
                        ],
                        [],
                    ),
                    ("Tablets", [], []),
                ],
            ),
            (
                "Computers",
                [
                    {"key": "brand", "label": "Brand", "type": "string", "required": True},
                    {"key": "ram_gb", "label": "RAM (GB)", "type": "number"},
                ],
                [
                    (
                        "Laptops",
                        [{"key": "screen_in", "label": "Screen (in)", "type": "number"}],
                        [],
                    ),
                    ("Desktops", [], []),
                ],
            ),
            ("TVs & Audio", [], []),
        ],
    ),
    (
        "Vehicles",
        [
            {"key": "make", "label": "Make", "type": "string", "required": True},
            {"key": "year", "label": "Year", "type": "number", "required": True},
        ],
        [
            (
                "Cars",
                [
                    {"key": "mileage_km", "label": "Mileage (km)", "type": "number"},
                    {
                        "key": "transmission",
                        "label": "Transmission",
                        "type": "enum",
                        "options": ["Automatic", "Manual"],
                    },
                    {
                        "key": "fuel",
                        "label": "Fuel",
                        "type": "enum",
                        "options": ["Petrol", "Diesel", "Hybrid", "Electric"],
                    },
                ],
                [],
            ),
            ("Motorbikes", [], []),
            ("Car Parts", [], []),
        ],
    ),
    (
        "Home & Furniture",
        [],
        [
            ("Furniture", [{"key": "material", "label": "Material", "type": "string"}], []),
            ("Appliances", [], []),
            ("Home Decor", [], []),
        ],
    ),
    (
        "Fashion",
        [
            {
                "key": "gender",
                "label": "Gender",
                "type": "enum",
                "options": ["Men", "Women", "Unisex", "Kids"],
            },
        ],
        [
            ("Clothing", [{"key": "size", "label": "Size", "type": "string"}], []),
            ("Shoes", [{"key": "size", "label": "Size", "type": "string"}], []),
            ("Bags & Accessories", [], []),
        ],
    ),
    (
        "Property",
        [
            {
                "key": "listing_type",
                "label": "For",
                "type": "enum",
                "options": ["Rent", "Sale"],
                "required": True,
            },
        ],
        [
            (
                "For Rent",
                [{"key": "bedrooms", "label": "Bedrooms", "type": "number"}],
                [],
            ),
            (
                "For Sale",
                [{"key": "bedrooms", "label": "Bedrooms", "type": "number"}],
                [],
            ),
        ],
    ),
]


class Command(BaseCommand):
    help = "Seed a realistic category tree with per-category attribute schemas."

    @transaction.atomic
    def handle(self, *args, **options):
        created, updated = self._seed(TREE, parent=None, order_base=0)
        self.stdout.write(
            self.style.SUCCESS(
                f"Categories seeded: {created} created, {updated} updated."
            )
        )

    def _seed(self, nodes, parent, order_base):
        created = updated = 0
        for order, (name, schema, children) in enumerate(nodes):
            slug = slugify(f"{parent.slug}-{name}" if parent else name)
            category, was_created = Category.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "parent": parent,
                    "attribute_schema": schema,
                    "order": order,
                },
            )
            created += int(was_created)
            updated += int(not was_created)
            c, u = self._seed(children, parent=category, order_base=0)
            created += c
            updated += u
        return created, updated
