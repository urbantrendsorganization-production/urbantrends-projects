from django.urls import path

from orgs import views

app_name = "orgs"

urlpatterns = [
    path("signup/", views.SignupView.as_view(), name="signup"),
    path("orgs/", views.OrganizationListView.as_view(), name="org-list"),
    path("orgs/<uuid:org_id>/", views.OrganizationDetailView.as_view(), name="org-detail"),
    path("orgs/<uuid:org_id>/members/", views.MembershipListView.as_view(), name="member-list"),
    path(
        "orgs/<uuid:org_id>/members/<uuid:membership_id>/",
        views.MembershipDetailView.as_view(),
        name="member-detail",
    ),
    path("orgs/<uuid:org_id>/invites/", views.StaffInviteListView.as_view(), name="invite-list"),
    path(
        "orgs/<uuid:org_id>/invites/<uuid:invite_id>/resend/",
        views.StaffInviteResendView.as_view(),
        name="invite-resend",
    ),
]
