import os

from django.db import migrations

from apps.roms.services import parse_rom_filename


def backfill(apps, schema_editor):
    ROM = apps.get_model("roms", "ROM")
    for rom in ROM.objects.filter(filename=""):
        if rom.extension and rom.title.lower().endswith(rom.extension):
            filename = rom.title
        else:
            filename = rom.title + rom.extension
        if len(filename) > 255:
            # Cut the part before the extension so the extension survives.
            stem, extension = os.path.splitext(filename)
            filename = stem[: 255 - len(extension)] + extension
        parsed = parse_rom_filename(filename)
        rom.filename = filename
        rom.title = parsed.title[:255]
        rom.tags = list(parsed.tags)
        rom.save(update_fields=["filename", "title", "tags"])


def restore(apps, schema_editor):
    # Lossy: a title edited after the upgrade is overwritten by the filename.
    ROM = apps.get_model("roms", "ROM")
    for rom in ROM.objects.exclude(filename=""):
        rom.title = rom.filename[:255]
        rom.filename = ""
        rom.tags = []
        rom.save(update_fields=["filename", "title", "tags"])


class Migration(migrations.Migration):

    dependencies = [
        ("roms", "0005_rom_filename_tags"),
    ]

    operations = [
        migrations.RunPython(backfill, restore),
    ]
