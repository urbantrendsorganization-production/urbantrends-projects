"""Org-scoped availability. The public route is registered in `public_api/urls.py`
so that everything under `/api/public/v1/` is listed in one file."""

from django.urls import path

from scheduling import views

app_name = "scheduling"

urlpatterns = [
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/staff/<uuid:staff_id>/availability/",
        views.StaffAvailabilityView.as_view(),
        name="staff-availability",
    ),
]
