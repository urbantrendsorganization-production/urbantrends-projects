import logging

from rest_framework.views import exception_handler as drf_exception_handler

from core.managers import CrossTenantQueryError

logger = logging.getLogger(__name__)


def exception_handler(exc, context):
    """A cross-tenant query is a bug, never a client error.

    Let it become a 500 and page someone, rather than degrading into an empty
    list that looks like "no results" in production.
    """
    if isinstance(exc, CrossTenantQueryError):
        logger.error("cross-tenant query blocked: %s", exc)
        raise exc
    return drf_exception_handler(exc, context)
