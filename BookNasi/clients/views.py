"""The §9 endpoints: find, export, erase.

## Who can reach these

Reading the client list is a managing role, like the rest of the org's
configuration. **Erasing is owner-only**, matching where slice 13 put the M-Pesa
credentials and for a related reason: it is irreversible and it is quiet. A
scrub cannot be undone, the row that remains looks like any other erased row,
and nobody else on the account would see that somebody had gone. A manager can
see the request, and cannot act on it.

## Export is a GET that returns a file

`Content-Disposition: attachment`, because the thing an owner has to do with it
is send it to a person, and a JSON body rendered in a browser tab is something
they then have to work out how to save. The filename carries the client id
rather than their name — an export of somebody's personal data should not put
that data in a filename that ends up in a downloads folder and a chat thread.
"""

from django.conf import settings
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from clients import erasure
from clients.models import Client, ScrubReason
from clients.serializers import ClientSerializer, ErasurePlanSerializer
from core.tenancy import OrgScopedMixin


class ClientListView(OrgScopedMixin, generics.ListAPIView):
    """The people this organization holds data about.

    Org-scoped, never shop-scoped — CLAUDE.md §3, and the reason §9 lands here
    rather than on a shop: the organization is the controller, and a data
    subject's record spans every branch they have visited.
    """

    serializer_class = ClientSerializer
    managing_roles_required = True

    def get_queryset(self):
        rows = (
            Client.objects.for_org(self.organization)
            .annotate(
                last_seen=Max("appointments__time_range__startswith"), visits=Count("appointments")
            )
            .order_by("-erasure_requested_at", "full_name", "phone")
        )
        search = self.request.query_params.get("q", "").strip()
        if search:
            rows = rows.filter(Q(full_name__icontains=search) | Q(phone__icontains=search))
        if self.request.query_params.get("requested") == "1":
            rows = rows.filter(erasure_requested_at__isnull=False, scrubbed_at__isnull=True)
        return rows


class ClientDetailView(OrgScopedMixin, generics.RetrieveUpdateAPIView):
    """No destroy. §9 says scrub, and `POST .../erase/` is where that lives.

    A `DELETE` here would be the wrong verb doing the right thing, which is how
    somebody eventually writes the cascade §9 forbids because the method name
    implied it.
    """

    serializer_class = ClientSerializer
    managing_roles_required = True
    lookup_url_kwarg = "client_id"

    def get_queryset(self):
        return Client.objects.for_org(self.organization)


class ClientExportView(OrgScopedMixin, APIView):
    """Everything held about one person, as a file they can be given."""

    managing_roles_required = True

    def get(self, request, org_id, client_id):
        client = generics.get_object_or_404(Client.objects.for_org(self.organization), pk=client_id)
        payload = erasure.export_for(client)
        response = JsonResponse(payload, json_dumps_params={"indent": 2})
        response["Content-Disposition"] = f'attachment; filename="client-{client.id}.json"'
        return response


class RetentionPolicyView(OrgScopedMixin, APIView):
    """The retention sentence, worded once and read from here.

    A separate endpoint rather than a field on the client list, because it is a
    property of the deployment and not of any client, and because the list is
    paginated — putting it on every page would be sending the same sentence
    twenty times to be shown once.

    Its whole purpose is that the settings screen does **not** restate it.
    §12 established the rule with the refund sentence: a policy worded in two
    places is a policy a shop can state one way to a client and another way to
    itself, and nobody notices until the two are compared in a complaint.
    """

    managing_roles_required = True

    def get(self, request, org_id):
        return Response(
            {
                "months_after_last_visit": settings.CLIENT_RETENTION_MONTHS,
                "statement": erasure.retention_statement(),
            }
        )


class ClientErasureView(OrgScopedMixin, APIView):
    """`GET` says what it will cost. `POST` does it.

    Two steps on purpose. The cost is not obvious — unspent credit stops being
    spendable — and a confirm dialog that had to guess at the number, or omit
    it, would be asking somebody to agree to something nobody had told them.
    """

    owner_role_required = True

    def _client(self):
        return generics.get_object_or_404(
            Client.objects.for_org(self.organization), pk=self.kwargs["client_id"]
        )

    def get(self, request, org_id, client_id):
        plan = erasure.plan_for(self._client())
        return Response(ErasurePlanSerializer(plan.__dict__).data)

    def post(self, request, org_id, client_id):
        client = self._client()
        was_requested = client.erasure_requested_at is not None
        erasure.erase(
            client,
            # The distinction is the audit trail. A request carries a statutory
            # clock and the shop acting unprompted does not, and a controller
            # asked to account for either needs them told apart.
            reason=ScrubReason.REQUESTED if was_requested else ScrubReason.SHOP,
        )
        return Response(ClientSerializer(client).data, status=status.HTTP_200_OK)
