from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.messaging.views import BlockView, ConversationViewSet, ReportView

app_name = "messaging"

router = DefaultRouter()
router.register("conversations", ConversationViewSet, basename="conversation")

urlpatterns = [
    *router.urls,
    path("users/<int:pk>/block/", BlockView.as_view(), name="block"),
    path("users/<int:pk>/report/", ReportView.as_view(), name="report"),
]
