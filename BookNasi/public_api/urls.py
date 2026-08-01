from django.urls import path

from public_api import views

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
]
