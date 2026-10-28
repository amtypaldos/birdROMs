from django.core.management.base import BaseCommand, CommandError

from apps.roms.library import get_library
from apps.roms.scanner import run_library_scan

COUNTERS = ("added", "changed", "missing", "restored", "skipped_multifile", "skipped_other")


class Command(BaseCommand):
    help = "Scan the ROM library now and print what changed. Exits 1 when the scan aborts or fails."

    def add_arguments(self, parser):
        parser.add_argument(
            "--accept-removals",
            action="store_true",
            help="Skip the safety guard and flag every vanished file missing.",
        )

    def handle(self, *args, accept_removals=False, **options):
        scan = run_library_scan(accept_removals=accept_removals, library=get_library())
        if scan is None:
            raise CommandError("Another library scan is already running.")
        for name in COUNTERS:
            self.stdout.write(f"{name}: {getattr(scan, name)}")
        if scan.unknown_folders:
            self.stdout.write("unknown folders: " + ", ".join(scan.unknown_folders))
        if scan.state != "ok":
            raise CommandError(f"Scan {scan.state}: {scan.message}")
