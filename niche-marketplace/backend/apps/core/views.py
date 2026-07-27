from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import services


class HealthView(APIView):
    """Liveness/readiness probe consumed by the frontend and by compose."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request: Request) -> Response:
        return Response(services.get_health())
