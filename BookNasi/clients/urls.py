from django.urls import path

from clients import views

app_name = "clients"

urlpatterns = [
    path("orgs/<uuid:org_id>/clients/", views.ClientListView.as_view(), name="client-list"),
    # Before `<uuid:client_id>` would match it, and a distinct segment anyway.
    path(
        "orgs/<uuid:org_id>/clients/retention/",
        views.RetentionPolicyView.as_view(),
        name="retention-policy",
    ),
    path(
        "orgs/<uuid:org_id>/clients/<uuid:client_id>/",
        views.ClientDetailView.as_view(),
        name="client-detail",
    ),
    # CLAUDE.md §9's export path and delete path, as two named actions rather
    # than verbs on the detail route. A `DELETE` that scrubbed instead of
    # deleting is the wrong shape wearing the right name.
    path(
        "orgs/<uuid:org_id>/clients/<uuid:client_id>/export/",
        views.ClientExportView.as_view(),
        name="client-export",
    ),
    path(
        "orgs/<uuid:org_id>/clients/<uuid:client_id>/erase/",
        views.ClientErasureView.as_view(),
        name="client-erase",
    ),
]
