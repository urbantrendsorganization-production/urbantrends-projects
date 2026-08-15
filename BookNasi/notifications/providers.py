"""The messaging interface, shaped so WhatsApp is a swap and not a rewrite.

CLAUDE.md §6: "Keep the provider behind an interface so SMS → WhatsApp Business
API is a swap, not a rewrite." That sentence is easy to satisfy badly. An
interface of `send(to, text)` is behind an interface and is still a rewrite,
for one reason:

**WhatsApp Business does not accept text.** It accepts a pre-approved template
name and a list of variables, and Meta reviews the template. A caller that hands
the provider a finished string forces the WhatsApp adapter to parse our own
sentences back apart into slots — and to keep doing so every time somebody
edits the copy.

So the contract here is `(template id, variables)`, never rendered text. The
**provider renders**. The SMS adapter renders from the local template table in
`notifications/templates.py`; a WhatsApp adapter maps `booking_confirmed` to
whatever Meta approved and passes the same variables through. Same call site,
different adapter, no shared string.

Two smaller decisions that come from the same place:

- **The link is a variable, not part of the template.** One link per message is
  the design's rule; building it at the call site means the token is minted once
  and recorded once.
- **Sender id is provider configuration.** `BOOKNASI` is an SMS concept. A
  WhatsApp adapter has a phone number id instead, and a caller that passed a
  sender would be passing something the next provider cannot use.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Outgoing:
    """One message to send. Template id and variables — never rendered text."""

    template: str
    to: str
    variables: dict = field(default_factory=dict)
    #: Our id for this send, echoed into logs and stored on the row. Not the
    #: provider's — that comes back on the receipt.
    reference: str = ""


@dataclass(frozen=True)
class DeliveryReceipt:
    """What the provider said. `accepted` is about handover, not delivery.

    No provider tells you synchronously that a phone received anything. This
    records that the gateway took it; a delivery-report webhook is a later
    slice and would update the row, not this object.
    """

    provider_message_id: str = ""
    accepted: bool = True
    error_code: str = ""
    error_detail: str = ""
    #: Whole shillings if the provider reports one. Messaging cost is a real
    #: line item — CLAUDE.md §6 — and a number nobody records is a number
    #: nobody manages.
    cost_kes: int | None = None


class MessageProvider(Protocol):
    """Two members. Anything wider makes the swap harder, not easier."""

    name: str

    def send(self, message: Outgoing) -> DeliveryReceipt: ...


class ConsoleProvider:
    """Development and tests. Renders through the same table the SMS adapter
    would, so a template that does not render fails here first."""

    name = "console"

    def __init__(self):
        self.sent = []

    def send(self, message):
        from notifications.templates import render

        body = render(message.template, message.variables)
        self.sent.append({"to": message.to, "template": message.template, "body": body})
        # Deliberately not logged. The body carries a name, a time and a phone
        # number; a console provider that prints it is a console provider
        # somebody runs in staging against real client data.
        return DeliveryReceipt(
            provider_message_id=f"console-{len(self.sent)}", accepted=True, cost_kes=0
        )


class SmsProvider:
    """The shape a real SMS gateway takes. Not wired to a vendor yet.

    Left unimplemented on purpose rather than half-integrated against a guessed
    API: there is no gateway account, and a `send` that posts to a URL nobody
    has tested is worse than one that says so. `settings.MESSAGE_PROVIDER`
    points at `ConsoleProvider` until there is an account, and the swap is one
    settings line — which is the whole claim this module is making.
    """

    name = "sms"

    def __init__(self, config=None):
        from django.conf import settings

        self.config = config or settings.SMS
        if not self.config.get("API_KEY"):
            raise NotConfigured(
                "SMS_API_KEY is not set. Set MESSAGE_PROVIDER to the console "
                "provider for local work, or supply gateway credentials."
            )

    def send(self, message):  # pragma: no cover — no gateway account yet
        raise NotConfigured("No SMS gateway is wired up yet.")


class NotConfigured(RuntimeError):
    pass


_provider = None


def get_provider():
    global _provider
    if _provider is None:
        from django.conf import settings
        from django.utils.module_loading import import_string

        _provider = import_string(settings.MESSAGE_PROVIDER)()
    return _provider


def reset_provider():
    """Drop the cached provider. For tests, and for a settings override."""
    global _provider
    _provider = None
