from django.urls import path

from public_api import views
from scheduling import views as scheduling_views

app_name = "public_api"

urlpatterns = [
    path("shops/<slug:slug>/", views.PublicShopDetailView.as_view(), name="shop-detail"),
    path(
        "shops/<slug:slug>/services/",
        views.PublicServiceListView.as_view(),
        name="service-list",
    ),
    path(
        "shops/<slug:slug>/services/<uuid:service_id>/staff/",
        views.PublicStaffListView.as_view(),
        name="staff-list",
    ),
    # Availability lives in the `scheduling` app but is routed here, so that
    # every unauthenticated path in the product is visible in one file.
    path(
        "shops/<slug:slug>/services/<uuid:service_id>/availability/",
        scheduling_views.PublicAvailabilityView.as_view(),
        name="availability",
    ),
    # Slice 5's write path. One POST is the whole confirm step.
    path("shops/<slug:slug>/holds/", views.HoldCreateView.as_view(), name="hold-create"),
    # Not shop-scoped: the id is unguessable and *is* the session, per
    # CLAUDE.md §12's "the link is the session". A client on the countdown
    # screen has an appointment id and no reason to carry a slug as well.
    path("holds/<uuid:hold_id>/", views.HoldDetailView.as_view(), name="hold-detail"),
    path(
        "holds/<uuid:hold_id>/release/",
        views.HoldReleaseView.as_view(),
        name="hold-release",
    ),
]
