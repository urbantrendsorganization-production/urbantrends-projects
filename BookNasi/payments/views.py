"""The M-Pesa callback endpoint. One view, and four unusual decisions.

**1. It always answers 200.** Malformed body, unknown CheckoutRequestID,
conflicting duplicate, exception in our own code — all 200. Safaricom retries
anything else, so a non-200 turns one bad body into a retry storm and one bug
into an outage. The outcome is in the response body for our own logs and is
never used as a status code.

**2. Nothing authenticates it, and a secret path segment stands in.** Safaricom
does not sign callbacks and does not offer mutual TLS. Without something, the
endpoint that confirms bookings is a public POST that anybody can forge — send
a `ResultCode: 0` for a guessed CheckoutRequestID and you have a free booking.
The token is configured once, with the shortcode, in the callback URL itself.
A wrong token is a 404 rather than a 200, because a misconfigured token must be
loudly broken; silently accepting it would mean discovering the problem when a
forged confirmation turns up.

**3. It is not throttled.** A 429 is a non-200 and therefore a retry. Rate
limiting the endpoint that tells us money arrived is rate limiting our own
revenue.

**4. It is CSRF-exempt and session-authentication-free.** There is no browser
and no user here.
"""

import logging

from django.conf import settings
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from payments.callbacks import handle_callback

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class MpesaCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    #: Empty on purpose. See decision 3 in the module docstring.
    throttle_classes = []

    def post(self, request, token):
        import secrets

        expected = settings.MPESA_CALLBACK_TOKEN
        # `compare_digest` rather than `==`: this is a shared secret in a URL,
        # and a timing-variable comparison on a public endpoint is free to probe.
        if not expected or not secrets.compare_digest(str(token), str(expected)):
            logger.error("m-pesa callback with a bad path token")
            raise Http404

        outcome = handle_callback(request.data)
        # 200 whatever happened. The outcome is for our logs, not for Safaricom.
        return Response(
            {"ResultCode": 0, "ResultDesc": "Accepted", "outcome": outcome},
            status=status.HTTP_200_OK,
        )
