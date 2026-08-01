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
]
