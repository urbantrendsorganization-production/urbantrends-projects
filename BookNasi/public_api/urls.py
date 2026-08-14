from django.urls import path

from public_api import lifecycle_views, views
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
    # Slice 6. Screen 5's "Resend the prompt", bounded in payments/stk.py.
    path(
        "holds/<uuid:hold_id>/resend/",
        views.HoldResendView.as_view(),
        name="hold-resend",
    ),
    # Slice 7, the lifecycle. Not shop-scoped and not id-scoped: the token *is*
    # the session (CLAUDE.md §12), and it resolves to exactly one appointment in
    # one tenant. `<str:token>` rather than a typed converter so a malformed
    # token reaches the view and gets the same 404 as a wrong one — a URL-level
    # rejection would be a different response for a different failure, which is
    # the existence oracle `lifecycle_views` exists to avoid.
    path("manage/<str:token>/", lifecycle_views.ManageDetailView.as_view(), name="manage-detail"),
    path(
        "manage/<str:token>/cancel/",
        lifecycle_views.ManageCancelView.as_view(),
        name="manage-cancel",
    ),
    path(
        "manage/<str:token>/reschedule/",
        lifecycle_views.ManageRescheduleView.as_view(),
        name="manage-reschedule",
    ),
    # The slotLost remedy. Keyed by support code, which is what screen 8 shows.
    path(
        "payments/<str:support_code>/repoint/",
        lifecycle_views.RepointView.as_view(),
        name="payment-repoint",
    ),
]
