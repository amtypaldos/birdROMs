from django.core.management.base import BaseCommand, CommandError

from apps.roms.handheld import InvalidMuxapp, install_bundled


class Command(BaseCommand):
    help = "Install the handheld package shipped in this image, if it differs from the published one."

    def handle(self, *args, **options):
        try:
            replaced = install_bundled()
        except InvalidMuxapp as exc:
            raise CommandError(str(exc)) from exc
        if replaced:
            self.stdout.write(self.style.SUCCESS("Installed the bundled handheld package."))
        else:
            self.stdout.write("Bundled handheld package unchanged.")
