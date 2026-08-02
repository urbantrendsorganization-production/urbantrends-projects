"""Org-scoped availability, the staff day and the walk-in.

The public availability route is registered in `public_api/urls.py` so that
everything under `/api/public/v1/` is listed in one file.
"""

from django.urls import path

from scheduling import views

app_name = "scheduling"

SHOP = "orgs/<uuid:org_id>/shops/<uuid:shop_id>/"

urlpatterns = [
    path(
        SHOP + "staff/<uuid:staff_id>/availability/",
        views.StaffAvailabilityView.as_view(),
        name="staff-availability",
    ),
    # The adoption screen. One GET renders Today.
    path(SHOP + "day/", views.StaffDayView.as_view(), name="staff-day"),
    # Three taps: one GET for taps 1 and 2, one POST for tap 3.
    path(SHOP + "walk-in/options/", views.WalkInOptionsView.as_view(), name="walk-in-options"),
    path(SHOP + "walk-in/", views.WalkInView.as_view(), name="walk-in"),
    path(
        SHOP + "appointments/<uuid:appointment_id>/",
        views.AppointmentDetailView.as_view(),
        name="appointment-detail",
    ),
    # Start, finish, no-show, cancel and every undo. One transition table, one
    # endpoint — see scheduling/transitions.py.
    path(
        SHOP + "appointments/<uuid:appointment_id>/status/",
        views.AppointmentStatusView.as_view(),
        name="appointment-status",
    ),
    # The name, asked after saving and never before.
    path(
        SHOP + "appointments/<uuid:appointment_id>/client/",
        views.AppointmentClientView.as_view(),
        name="appointment-client",
    ),
]
