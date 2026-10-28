import logging

from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from birdroms.tasks import scrape_rom_cover

from .models import ROM

logger = logging.getLogger(__name__)


@admin.register(ROM)
class ROMAdmin(admin.ModelAdmin):
    list_display = ("thumbnail", "title", "platform", "extension", "uploaded_by", "uploaded_at")
    list_display_links = ("thumbnail", "title")
    list_filter = ("platform",)
    search_fields = ("title", "filename")
    list_select_related = ("uploaded_by",)
    # Editing filename would silently change download names, and with them the device's save keys.
    readonly_fields = ("thumbnail", "extension", "filename", "tags", "cover_art_source", "uploaded_at")
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
        queued = failed = 0
        for rom_id in queryset.values_list("pk", flat=True):
            try:
                scrape_rom_cover(rom_id)
            except Exception:
                # A broker outage must not turn the admin action into a 500.
                logger.exception("Could not enqueue the cover art scrape for ROM %s", rom_id)
                failed += 1
            else:
                queued += 1
        self.message_user(request, f"Queued cover art scraping for {queued} ROM{'' if queued == 1 else 's'}.")
        if failed:
            self.message_user(
                request,
                f"Could not queue cover art scraping for {failed} ROM{'' if failed == 1 else 's'}; see the server log.",
                level=messages.ERROR,
            )
