from django.contrib import admin
from django.urls import include, path

from core.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    # Authenticated, org-scoped. Staff and owner.
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/", include("orgs.urls")),
    # /api/public/v1/ is deliberately absent until slice 5. When it lands it gets
    # its own serializers — CLAUDE.md §1. A shared serializer with an
    # `if request.user` branch is how tenant data leaks.
]
