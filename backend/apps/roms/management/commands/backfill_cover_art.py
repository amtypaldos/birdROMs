from django.core.management.base import BaseCommand

from apps.roms.cover_art import safe_fetch_cover_for_rom
from apps.roms.models import ROM


class Command(BaseCommand):
    help = "Scrape and store cover art for ROMs that have none (uses COVER_ART_PROVIDERS)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Re-scrape every ROM, replacing existing art.")

    def handle(self, *args, force=False, **options):
        roms = ROM.objects.order_by("pk")
        if not force:
            roms = roms.filter(cover_art="")
        found = missing = 0
        for rom in roms.iterator():
            if safe_fetch_cover_for_rom(rom):
                found += 1
                self.stdout.write(f"  found: {rom.title} ({rom.cover_art_source})")
            else:
                missing += 1
                self.stdout.write(f"  none:  {rom.title}")
        self.stdout.write(self.style.SUCCESS(f"Cover art saved for {found} ROM(s); {missing} without a match."))
