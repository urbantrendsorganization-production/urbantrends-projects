from django.urls import path

from payments import views

app_name = "payments"

urlpatterns = [
    # The token is part of the URL Safaricom is configured with. See
    # payments/views.py, decision 2.
    path("callback/<str:token>/", views.MpesaCallbackView.as_view(), name="mpesa-callback"),
]
