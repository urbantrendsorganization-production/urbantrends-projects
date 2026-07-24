from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.messaging import services
from apps.messaging.permissions import IsParticipant
from apps.messaging.serializers import (
    ConversationSerializer,
    MessageCreateSerializer,
    MessageSerializer,
    ReportSerializer,
    StartConversationSerializer,
)

User = get_user_model()


class ConversationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """The signed-in user's message threads.

    - list/retrieve: threads the user is a participant in.
    - create: open (or re-open) the thread for a listing.
    - messages: read the thread (marks it read) or post to it.
    - unread_count: total unread across all threads (for the navbar badge).
    """

    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated, IsParticipant]

    def get_queryset(self):
        return services.conversations_for(self.request.user).prefetch_related(
            "messages"
        )

    def create(self, request: Request) -> Response:
        serializer = StartConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation = services.get_or_start_conversation(
            listing=serializer.validated_data["listing"], buyer=request.user
        )
        data = ConversationSerializer(
            self.get_queryset().get(pk=conversation.pk),
            context=self.get_serializer_context(),
        ).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def unread_count(self, request: Request) -> Response:
        return Response({"count": services.unread_count(request.user)})

    @action(detail=True, methods=["get", "post"])
    def messages(self, request: Request, pk=None) -> Response:
        conversation = self.get_object()

        if request.method == "POST":
            serializer = MessageCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            message = services.post_message(
                conversation=conversation,
                sender=request.user,
                body=serializer.validated_data["body"],
            )
            return Response(
                MessageSerializer(message, context=self.get_serializer_context()).data,
                status=status.HTTP_201_CREATED,
            )

        # GET: opening the thread marks the other party's messages read.
        services.mark_conversation_read(
            conversation=conversation, reader=request.user
        )
        messages = conversation.messages.select_related("sender")
        return Response(
            MessageSerializer(
                messages, many=True, context=self.get_serializer_context()
            ).data
        )


class BlockView(APIView):
    """Block (POST) or unblock (DELETE) another user."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        target = get_object_or_404(User, pk=pk, is_active=True)
        services.block_user(blocker=request.user, blocked=target)
        return Response({"detail": "User blocked.", "blocked": True})

    def delete(self, request: Request, pk: int) -> Response:
        target = get_object_or_404(User, pk=pk)
        services.unblock_user(blocker=request.user, blocked=target)
        return Response({"detail": "User unblocked.", "blocked": False})


class ReportView(APIView):
    """File a report against another user (reviewed in the admin queue)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        target = get_object_or_404(User, pk=pk, is_active=True)
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.report_user(
            reporter=request.user,
            reported=target,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(
            {"detail": "Thanks — this user has been reported."},
            status=status.HTTP_201_CREATED,
        )
