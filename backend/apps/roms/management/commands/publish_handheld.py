from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.roms.handheld import InvalidMuxapp, publish_package


class Command(BaseCommand):
    help = "Publish a handheld build (birdROMs.muxapp) so signed-in users can download it from the website."

    def add_arguments(self, parser):
        parser.add_argument("package", help="Path to the .muxapp built by `just package` in the handheld repo.")

    def handle(self, *args, package, **options):
        source = Path(package)
        try:
            target = publish_package(source)
        except InvalidMuxapp as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Published {source.name} ({target.stat().st_size} bytes) to {target}."))
