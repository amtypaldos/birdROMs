import os
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.roms.handheld import InvalidMuxapp, handheld_path, validate_muxapp


class Command(BaseCommand):
    help = "Publish a handheld build (birdROMs.muxapp) so signed-in users can download it from the website."

    def add_arguments(self, parser):
        parser.add_argument("package", help="Path to the .muxapp built by `just package` in the handheld repo.")

    def handle(self, *args, package, **options):
        source = Path(package)
        if not source.is_file():
            raise CommandError(f"{source} does not exist.")
        try:
            validate_muxapp(source)
        except InvalidMuxapp as exc:
            raise CommandError(str(exc)) from exc
        target = handheld_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        # Copy beside the target, then rename, so a download never sees a half-written file.
        partial = target.with_name(target.name + ".partial")
        shutil.copyfile(source, partial)
        os.replace(partial, target)
        self.stdout.write(self.style.SUCCESS(f"Published {source.name} ({target.stat().st_size} bytes) to {target}."))
