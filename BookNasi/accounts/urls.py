from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("csrf/", views.CsrfView.as_view(), name="csrf"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("me/", views.MeView.as_view(), name="me"),
    path("invite/accept/", views.InviteAcceptView.as_view(), name="invite-accept"),
]
