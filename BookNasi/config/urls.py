from django.contrib import admin
from django.urls import include, path

from core.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    # Authenticated, org-scoped. Staff and owner.
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/", include("orgs.urls")),
    path("api/v1/", include("shops.urls")),
    path("api/v1/", include("scheduling.urls")),
    path("api/v1/", include("clients.urls")),
    # The owner dashboard. Owner/manager only — see reporting/views.py.
    path("api/v1/", include("reporting.urls")),
    # Unauthenticated, shop-scoped by slug, consumed by the widget and by any
    # third-party integrator. Its serializers live in a separate module and
    # share no code with the org-scoped ones above — CLAUDE.md §1. A shared
    # serializer with an `if request.user` branch is how tenant data leaks.
    path("api/public/v1/", include("public_api.urls")),
    # Safaricom's callback. Not under `public/v1` because it is not part of the
    # public booking API — no integrator calls it, its shape is Safaricom's, and
    # it answers 200 to everything. See payments/views.py.
    path("api/mpesa/", include("payments.urls")),
]
