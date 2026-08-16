from django.urls import path

from shops import views

app_name = "shops"

urlpatterns = [
    path("orgs/<uuid:org_id>/shops/", views.ShopListCreateView.as_view(), name="shop-list"),
    path(
        "orgs/<uuid:org_id>/shops/check-slug/",
        views.SlugAvailabilityView.as_view(),
        name="slug-check",
    ),
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/",
        views.ShopDetailView.as_view(),
        name="shop-detail",
    ),
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/open-on/",
        views.ShopOpenOnView.as_view(),
        name="shop-open-on",
    ),
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/readiness/",
        views.ShopReadinessView.as_view(),
        name="shop-readiness",
    ),
    # Owner-only: whose M-Pesa account this shop's deposits land in.
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/mpesa/",
        views.ShopMpesaView.as_view(),
        name="shop-mpesa",
    ),
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/mpesa/disconnect/",
        views.ShopMpesaDisconnectView.as_view(),
        name="shop-mpesa-disconnect",
    ),
    # Shop children
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/opening-hours/",
        views.OpeningHoursListCreateView.as_view(),
        name="opening-hours-list",
    ),
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/opening-hours/<uuid:pk>/",
        views.OpeningHoursDetailView.as_view(),
        name="opening-hours-detail",
    ),
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/closures/",
        views.ClosureListCreateView.as_view(),
        name="closure-list",
    ),
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/closures/<uuid:pk>/",
        views.ClosureDetailView.as_view(),
        name="closure-detail",
    ),
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/staff/",
        views.StaffListCreateView.as_view(),
        name="staff-list",
    ),
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/staff/<uuid:staff_id>/",
        views.StaffDetailView.as_view(),
        name="staff-detail",
    ),
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/services/",
        views.ServiceListCreateView.as_view(),
        name="service-list",
    ),
    path(
        "orgs/<uuid:org_id>/shops/<uuid:shop_id>/services/<uuid:service_id>/",
        views.ServiceDetailView.as_view(),
        name="service-detail",
    ),
    # Staff children
    path(
        "orgs/<uuid:org_id>/staff/<uuid:staff_id>/working-hours/",
        views.WorkingHoursListCreateView.as_view(),
        name="working-hours-list",
    ),
    path(
        "orgs/<uuid:org_id>/staff/<uuid:staff_id>/working-hours/<uuid:pk>/",
        views.WorkingHoursDetailView.as_view(),
        name="working-hours-detail",
    ),
    path(
        "orgs/<uuid:org_id>/staff/<uuid:staff_id>/leave/",
        views.LeaveListCreateView.as_view(),
        name="leave-list",
    ),
    path(
        "orgs/<uuid:org_id>/staff/<uuid:staff_id>/leave/<uuid:pk>/",
        views.LeaveDetailView.as_view(),
        name="leave-detail",
    ),
    path(
        "orgs/<uuid:org_id>/staff/<uuid:staff_id>/services/",
        views.StaffServiceListCreateView.as_view(),
        name="staff-service-list",
    ),
    path(
        "orgs/<uuid:org_id>/staff/<uuid:staff_id>/services/<uuid:pk>/",
        views.StaffServiceDetailView.as_view(),
        name="staff-service-detail",
    ),
]
