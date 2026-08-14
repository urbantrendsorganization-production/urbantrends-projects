"""Message rows, read-only.

Answers "did the client get the link?" without anybody guessing, and makes the
cost line visible — CLAUDE.md §6 prices messaging as a real expense, and an
expense nobody can see is one nobody manages.

The rendered body is deliberately absent, here and in the model: it is
reconstructible from the template and the variables, and a second durable copy
of a client's name and time exists only for convenience (CLAUDE.md §9).
"""

from django.contrib import admin

from notifications.models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("template", "to", "status", "provider", "cost_kes", "sent_at")
    list_filter = ("status", "template", "provider")
    search_fields = ("to", "provider_message_id")
    ordering = ("-created_at",)
    readonly_fields = [field.name for field in Message._meta.fields]

    def get_queryset(self, request):
        return Message.objects.unscoped().select_related("appointment")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
