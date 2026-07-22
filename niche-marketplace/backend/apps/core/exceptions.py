"""Consistent API error envelope: ``{"detail": ..., "code": ...}``."""
from rest_framework.views import exception_handler


def envelope_exception_handler(exc, context):
    """Normalise every DRF error to a flat ``{detail, code}`` shape.

    DRF's default handler returns varied structures; we flatten them so
    clients can rely on a single contract across the whole API.
    """
    response = exception_handler(exc, context)
    if response is None:
        return None

    code = getattr(exc, "default_code", None) or "error"
    detail = response.data

    # Unwrap the common ``{"detail": "..."}`` case to avoid double nesting.
    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        detail = detail["detail"]

    response.data = {"detail": detail, "code": code}
    return response
