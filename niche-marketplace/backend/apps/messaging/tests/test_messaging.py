"""Messaging: threads, read state, unread counts, blocking, and permissions."""
import pytest

from apps.messaging.models import Block, Conversation, Message, Report

CONVERSATIONS = "/api/v1/conversations/"


def start(client, listing):
    return client.post(CONVERSATIONS, {"listing": listing.pk}, format="json")


def messages_url(pk):
    return f"{CONVERSATIONS}{pk}/messages/"


# --- starting threads ------------------------------------------------------


@pytest.mark.django_db
def test_buyer_starts_thread_with_seller(api_client, buyer, listing):
    api_client.force_authenticate(buyer)
    res = start(api_client, listing)
    assert res.status_code == 201, res.data
    assert res.data["other_party"]["id"] == listing.seller_id
    assert Conversation.objects.count() == 1


@pytest.mark.django_db
def test_one_thread_per_buyer_per_listing(api_client, buyer, listing):
    api_client.force_authenticate(buyer)
    first = start(api_client, listing).data["id"]
    second = start(api_client, listing).data["id"]
    assert first == second
    assert Conversation.objects.count() == 1


@pytest.mark.django_db
def test_seller_cannot_message_own_listing(api_client, seller, listing):
    api_client.force_authenticate(seller)
    res = start(api_client, listing)
    assert res.status_code == 400
    assert Conversation.objects.count() == 0


@pytest.mark.django_db
def test_anonymous_cannot_start_thread(api_client, listing):
    assert start(api_client, listing).status_code == 401


# --- messaging + read state ------------------------------------------------


@pytest.mark.django_db
def test_message_roundtrip_and_read_state(api_client, buyer, seller, listing):
    api_client.force_authenticate(buyer)
    convo_id = start(api_client, listing).data["id"]

    sent = api_client.post(messages_url(convo_id), {"body": "Still available?"}, format="json")
    assert sent.status_code == 201
    assert sent.data["is_mine"] is True
    assert sent.data["read_at"] is None

    # Seller sees the thread with one unread.
    api_client.force_authenticate(seller)
    convo = next(
        c for c in api_client.get(CONVERSATIONS).data["results"] if c["id"] == convo_id
    )
    assert convo["unread"] == 1
    assert convo["last_message"]["body"] == "Still available?"

    # Opening the thread marks it read.
    thread = api_client.get(messages_url(convo_id))
    assert thread.status_code == 200
    assert len(thread.data) == 1
    assert thread.data[0]["is_mine"] is False
    assert Message.objects.get().read_at is not None


@pytest.mark.django_db
def test_unread_count_endpoint(api_client, buyer, seller, listing):
    api_client.force_authenticate(buyer)
    convo_id = start(api_client, listing).data["id"]
    api_client.post(messages_url(convo_id), {"body": "hi"}, format="json")
    api_client.post(messages_url(convo_id), {"body": "there"}, format="json")

    # Sender has nothing unread; recipient has two.
    assert api_client.get(f"{CONVERSATIONS}unread_count/").data["count"] == 0
    api_client.force_authenticate(seller)
    assert api_client.get(f"{CONVERSATIONS}unread_count/").data["count"] == 2

    # After reading, it clears.
    api_client.get(messages_url(convo_id))
    assert api_client.get(f"{CONVERSATIONS}unread_count/").data["count"] == 0


@pytest.mark.django_db
def test_empty_message_rejected(api_client, buyer, listing):
    api_client.force_authenticate(buyer)
    convo_id = start(api_client, listing).data["id"]
    res = api_client.post(messages_url(convo_id), {"body": "   "}, format="json")
    assert res.status_code == 400


# --- permissions -----------------------------------------------------------


@pytest.mark.django_db
def test_non_participant_cannot_read_thread(api_client, buyer, stranger, listing):
    api_client.force_authenticate(buyer)
    convo_id = start(api_client, listing).data["id"]

    api_client.force_authenticate(stranger)
    # Not in the stranger's queryset → 404.
    assert api_client.get(messages_url(convo_id)).status_code == 404
    assert stranger.id not in (
        c["id"] for c in api_client.get(CONVERSATIONS).data["results"]
    )


# --- blocking & reporting --------------------------------------------------


@pytest.mark.django_db
def test_block_prevents_new_thread(api_client, buyer, seller, listing):
    # Seller blocks the buyer.
    api_client.force_authenticate(seller)
    assert api_client.post(f"/api/v1/users/{buyer.id}/block/").status_code == 200
    assert Block.objects.filter(blocker=seller, blocked=buyer).exists()

    # Buyer can no longer open a thread.
    api_client.force_authenticate(buyer)
    res = start(api_client, listing)
    assert res.status_code == 403
    assert res.data["code"] == "messaging_blocked"


@pytest.mark.django_db
def test_block_freezes_existing_thread(api_client, buyer, seller, listing):
    api_client.force_authenticate(buyer)
    convo_id = start(api_client, listing).data["id"]
    api_client.post(messages_url(convo_id), {"body": "hello"}, format="json")

    # Seller blocks buyer; buyer can't post further.
    api_client.force_authenticate(seller)
    api_client.post(f"/api/v1/users/{buyer.id}/block/")
    api_client.force_authenticate(buyer)
    res = api_client.post(messages_url(convo_id), {"body": "you there?"}, format="json")
    assert res.status_code == 403


@pytest.mark.django_db
def test_unblock_restores_messaging(api_client, buyer, seller, listing):
    api_client.force_authenticate(seller)
    api_client.post(f"/api/v1/users/{buyer.id}/block/")
    api_client.delete(f"/api/v1/users/{buyer.id}/block/")

    api_client.force_authenticate(buyer)
    assert start(api_client, listing).status_code == 201


@pytest.mark.django_db
def test_report_user(api_client, buyer, seller):
    api_client.force_authenticate(buyer)
    res = api_client.post(
        f"/api/v1/users/{seller.id}/report/", {"reason": "Scam"}, format="json"
    )
    assert res.status_code == 201
    report = Report.objects.get()
    assert report.reporter_id == buyer.id and report.reported_id == seller.id
    assert report.reason == "Scam"
