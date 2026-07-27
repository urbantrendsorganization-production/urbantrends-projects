from django.contrib import admin

from apps.messaging.models import Block, Conversation, Message, Report


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "buyer", "seller", "last_message_at")
    search_fields = ("listing__title", "buyer__email", "seller__email")
    raw_id_fields = ("listing", "buyer", "seller")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "read_at", "created_at")
    raw_id_fields = ("conversation", "sender")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "reporter", "reported", "created_at")
    search_fields = ("reporter__email", "reported__email", "reason")
    raw_id_fields = ("reporter", "reported")


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("id", "blocker", "blocked", "created_at")
    raw_id_fields = ("blocker", "blocked")
