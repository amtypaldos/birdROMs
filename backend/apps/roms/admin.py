from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from birdroms.tasks import scrape_rom_cover

from .models import ROM


@admin.register(ROM)
class ROMAdmin(admin.ModelAdmin):
    list_display = ("thumbnail", "title", "platform", "extension", "uploaded_by", "uploaded_at")
    list_display_links = ("thumbnail", "title")
    list_filter = ("platform",)
    search_fields = ("title",)
    list_select_related = ("uploaded_by",)
    readonly_fields = ("thumbnail", "extension", "cover_art_source", "uploaded_at")
    actions = ("rescrape_cover_art",)

    @admin.display(description="Cover")
    def thumbnail(self, obj):
        if not obj.pk or not obj.cover_art:
            return "-"
        # Served through the authenticated cover endpoint, so it works with any storage backend.
        return format_html(
            '<img src="{}" alt="{}" style="height: 64px; width: auto;">',
            reverse("rom-cover", args=[obj.pk]),
            obj.title,
        )

    @admin.action(description="Re-scrape cover art for selected ROMs")
    def rescrape_cover_art(self, request, queryset):
        queued = 0
        for rom_id in queryset.values_list("pk", flat=True):
            scrape_rom_cover(rom_id)
            queued += 1
        self.message_user(request, f"Queued cover art scraping for {queued} ROM{'' if queued == 1 else 's'}.")
