from django.contrib import admin

from apps.catalog.models import Category, Listing, ListingImage


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "parent", "depth", "order"]
    list_filter = ["parent"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ["name"]}

    @admin.display(description="Depth")
    def depth(self, obj: Category) -> int:
        return obj.depth


class ListingImageInline(admin.TabularInline):
    model = ListingImage
    extra = 0
    fields = ["image", "thumbnail", "order"]
    readonly_fields = ["thumbnail"]


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ["title", "seller", "category", "price", "currency", "status", "is_deleted"]
    list_filter = ["status", "condition", "is_deleted", "category"]
    search_fields = ["title", "description"]
    autocomplete_fields = ["category", "seller"]
    readonly_fields = ["created_at", "updated_at", "published_at", "deleted_at"]
    inlines = [ListingImageInline]
