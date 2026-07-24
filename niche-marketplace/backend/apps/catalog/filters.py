"""Directory filtering for the public listings feed.

One place builds the queryset behind ``GET /api/v1/listings/`` so the browse
page, its facets, and the tests all agree on what each query parameter means.
Everything here is additive: filters combine with AND, and an absent or
malformed parameter is simply ignored rather than erroring — a forgiving
directory beats a fussy one.
"""
from decimal import Decimal, InvalidOperation

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F, QuerySet

from apps.catalog.models import SEARCH_CONFIG, Category, Condition

# Query-parameter prefix that marks a category-specific attribute filter,
# e.g. ``?attr_brand=Samsung`` / ``?attr_year=2016``.
ATTR_PREFIX = "attr_"


def _coerce_attr(field: dict, raw: str):
    """Turn a raw query-string value into the JSON type the attribute is stored
    as, so a JSONB containment match actually hits. Returns ``None`` (skip the
    filter) if the value can't be coerced.
    """
    ftype = field["type"]
    if ftype == "number":
        try:
            return int(raw) if raw.isdigit() else float(raw)
        except (TypeError, ValueError):
            return None
    if ftype == "boolean":
        if raw in ("true", "false"):
            return raw == "true"
        return None
    # string / enum compare as-is (enum values are matched exactly).
    return raw


def _resolve_category(params) -> Category | None:
    """The category the ``category`` param points at, or ``None``."""
    raw = params.get("category")
    if not raw:
        return None
    try:
        return Category.objects.get(pk=int(raw))
    except (ValueError, Category.DoesNotExist):
        return None


def apply_search(qs: QuerySet, params) -> QuerySet:
    """Full-text filter + relevance annotation for the ``q`` parameter.

    Uses ``websearch`` query syntax (quoted phrases, ``-exclude`` all work) and
    annotates ``rank`` so callers can order by relevance.
    """
    q = (params.get("q") or "").strip()
    if not q:
        return qs
    query = SearchQuery(q, config=SEARCH_CONFIG, search_type="websearch")
    return qs.filter(search_vector=query).annotate(
        rank=SearchRank(F("search_vector"), query)
    )


def apply_filters(qs: QuerySet, params) -> QuerySet:
    """Apply every directory facet present in ``params`` to ``qs``.

    Expects a queryset already scoped to publicly visible listings; layers on
    keyword, category subtree, price, condition, location, and attribute
    filters. Order of application doesn't matter — all are AND-combined.
    """
    qs = apply_search(qs, params)

    category = _resolve_category(params)
    if category is not None:
        # Include the whole subtree, so "Electronics" also returns "Laptops".
        qs = qs.filter(category_id__in=category.descendant_ids())

    qs = _apply_price(qs, params)
    qs = _apply_condition(qs, params)

    location = (params.get("location") or "").strip()
    if location:
        qs = qs.filter(location__icontains=location)

    if category is not None:
        qs = _apply_attributes(qs, params, category)

    return qs


def _apply_price(qs: QuerySet, params) -> QuerySet:
    for name, lookup in (("price_min", "price__gte"), ("price_max", "price__lte")):
        raw = params.get(name)
        if raw:
            try:
                qs = qs.filter(**{lookup: Decimal(raw)})
            except (InvalidOperation, TypeError):
                pass
    return qs


def _apply_condition(qs: QuerySet, params) -> QuerySet:
    # Accept repeated (?condition=new&condition=good) or comma-separated values.
    raw = params.getlist("condition") if hasattr(params, "getlist") else []
    if len(raw) == 1 and "," in raw[0]:
        raw = raw[0].split(",")
    valid = [c for c in (v.strip() for v in raw) if c in Condition.values]
    if valid:
        qs = qs.filter(condition__in=valid)
    return qs


def _apply_attributes(qs: QuerySet, params, category: Category) -> QuerySet:
    """AND together ``attr_<key>=value`` filters via a single JSONB containment.

    Only keys defined in the category's effective schema are honoured, and each
    value is coerced to its declared JSON type so the ``@>`` match lands.
    """
    schema = {f["key"]: f for f in category.effective_schema()}
    wanted: dict = {}
    for name, raw in params.items():
        if not name.startswith(ATTR_PREFIX):
            continue
        key = name[len(ATTR_PREFIX):]
        field = schema.get(key)
        if field is None:
            continue
        value = _coerce_attr(field, raw)
        if value is not None:
            wanted[key] = value
    if wanted:
        qs = qs.filter(attributes__contains=wanted)
    return qs


def has_search(params) -> bool:
    """Whether a non-empty keyword query is present (drives default sort)."""
    return bool((params.get("q") or "").strip())
