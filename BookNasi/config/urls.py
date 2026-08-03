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
    # Unauthenticated, shop-scoped by slug, consumed by the widget and by any
    # third-party integrator. Its serializers live in a separate module and
    # share no code with the org-scoped ones above — CLAUDE.md §1. A shared
    # serializer with an `if request.user` branch is how tenant data leaks.
    path("api/public/v1/", include("public_api.urls")),
]
