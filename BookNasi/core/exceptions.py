import logging

from django.http import Http404
from rest_framework.views import exception_handler as drf_exception_handler

from core.cors import PUBLIC_PREFIX
from core.managers import CrossTenantQueryError

logger = logging.getLogger(__name__)

#: What a 404 says on the unauthenticated surface.
#:
#: DRF turns an `Http404` into a `NotFound` carrying the exception's own text,
#: and `get_object_or_404` writes that text for you: "No Shop matches the given
#: query." That is a useful sentence for us and a bewildering one for a client —
#: it names a database model, in a booking widget, on a salon's own website
#: (slice 10), to somebody who arrived from a WhatsApp link and cannot act on
#: any of it.
#:
#: The public surface has no deliberate 404 copy of its own to lose: every 404
#: under it is either a bare `Http404` or one Django generated. So they are all
#: normalised to one sentence that is true of every case it covers — a shop slug
#: that does not resolve, a hold that has gone, a manage link that has expired —
#: and that names the only thing the reader can actually do.
#:
#: Deliberately vague about *which* thing was not found, and that is not
#: politeness: `lifecycle_views` returns the same 404 for a malformed token and
#: a wrong one precisely so the endpoint is not an existence oracle, and a
#: message that distinguished them would hand back what the status code
#: withholds.
PUBLIC_NOT_FOUND = "We can't find that. The link may be out of date — ask the shop for a new one."


def exception_handler(exc, context):
    """Two rules: a cross-tenant query is a bug, and a 404 is not ORM-speak."""
    if isinstance(exc, CrossTenantQueryError):
        # Never a client error. Let it become a 500 and page someone, rather
        # than degrading into an empty list that looks like "no results" in
        # production.
        logger.error("cross-tenant query blocked: %s", exc)
        raise exc

    response = drf_exception_handler(exc, context)

    if isinstance(exc, Http404) and response is not None:
        request = context.get("request")
        if request is not None and request.path.startswith(PUBLIC_PREFIX):
            response.data = {"detail": PUBLIC_NOT_FOUND}

    return response
