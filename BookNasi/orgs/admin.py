from django.contrib import admin

from orgs.models import Membership, Organization, StaffInvite


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "owner", "subscription_status", "created_at"]
    search_fields = ["name", "slug"]


class OrgScopedAdmin(admin.ModelAdmin):
    """Admin is the one place CLAUDE.md §3 permits a cross-org read."""

    def get_queryset(self, request):
        return self.model.objects.unscoped().select_related("organization")


@admin.register(Membership)
class MembershipAdmin(OrgScopedAdmin):
    list_display = ["user", "organization", "role", "is_active", "accepted_at"]
    list_filter = ["role", "is_active"]


@admin.register(StaffInvite)
class StaffInviteAdmin(OrgScopedAdmin):
    list_display = ["phone", "organization", "role", "expires_at", "accepted_at", "sent_count"]
    list_filter = ["role"]
    # The hash is not a secret, but showing it invites someone to try using it.
    exclude = ["token_hash"]
