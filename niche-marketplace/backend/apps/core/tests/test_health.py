import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_endpoint_reports_ok():
    client = APIClient()
    response = client.get("/api/v1/health/")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["services"]["database"] == "up"
    assert "version" in body
