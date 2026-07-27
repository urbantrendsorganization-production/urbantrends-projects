"""Cursor pagination for the listings directory.

Cursor (keyset) pagination keeps deep browsing cheap and stable even as new
listings arrive mid-scroll — no rows skipped or repeated the way offset paging
drifts. The sort order is chosen per-request from ``?sort=`` and always carries
a unique ``id`` tiebreaker so the cursor position is well defined.
"""
from rest_framework.pagination import CursorPagination


class ListingCursorPagination(CursorPagination):
    page_size = 24
    max_page_size = 60
    page_size_query_param = "page_size"
    cursor_query_param = "cursor"
    # Default; overridden per-request by get_ordering below.
    ordering = ("-created_at", "-id")

    # Public sort options → order_by tuples. Each ends in a unique field so the
    # ordering is total (required for a stable cursor).
    SORTS = {
        "newest": ("-created_at", "-id"),
        "price_asc": ("price", "id"),
        "price_desc": ("-price", "-id"),
        "relevance": ("-rank", "-id"),
    }

    def get_ordering(self, request, queryset, view):
        sort = request.query_params.get("sort")
        # Relevance only makes sense (and only annotates ``rank``) when there's a
        # keyword query; otherwise fall back to newest.
        has_q = bool((request.query_params.get("q") or "").strip())
        if sort not in self.SORTS or (sort == "relevance" and not has_q):
            sort = "relevance" if (has_q and sort is None) else "newest"
        return self.SORTS[sort]
