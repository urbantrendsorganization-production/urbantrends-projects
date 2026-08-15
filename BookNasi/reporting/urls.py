from django.urls import path

from reporting import views

app_name = "reporting"

urlpatterns = [
    path("orgs/<uuid:org_id>/report/", views.ReportView.as_view(), name="report"),
]
