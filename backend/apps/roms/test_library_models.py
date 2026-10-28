from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.roms.models import ROM, LibraryScan


class RomLibraryFieldsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u", password="pw")

    def make_rom(self, name="ROMS/SFC/Game (USA).smc", **kwargs):
        rom = ROM(title="Game", uploaded_by=self.user, **kwargs)
        rom.file.name = name
        rom.save()
        return rom

    def test_library_relative_name_is_kept(self):
        rom = self.make_rom()
        rom.refresh_from_db()
        self.assertEqual(rom.file.name, "ROMS/SFC/Game (USA).smc")

    def test_file_name_is_unique(self):
        self.make_rom()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_rom()

    def test_defaults(self):
        rom = self.make_rom()
        self.assertFalse(rom.missing)
        self.assertEqual(rom.source, "upload")
        self.assertEqual(rom.cover_path, "")
        self.assertIsNone(rom.size_bytes)
        self.assertIsNone(rom.modified_at)

    def test_uploaded_by_nullable_and_set_null_on_user_delete(self):
        orphan = self.make_rom("ROMS/GBA/a.gba")
        orphan.uploaded_by = None
        orphan.save()
        owned = self.make_rom("ROMS/GBA/b.gba")
        self.user.delete()
        owned.refresh_from_db()
        self.assertIsNone(owned.uploaded_by)


class LibraryScanTests(TestCase):
    def test_first_is_newest(self):
        LibraryScan.objects.create(state="ok")
        newest = LibraryScan.objects.create(state="running")
        self.assertEqual(LibraryScan.objects.first(), newest)

    def test_defaults(self):
        scan = LibraryScan.objects.create(state="running")
        self.assertIsNone(scan.finished_at)
        self.assertEqual(
            (scan.added, scan.changed, scan.missing, scan.restored, scan.skipped_multifile, scan.skipped_other),
            (0, 0, 0, 0, 0, 0),
        )
        self.assertEqual(scan.unknown_folders, [])
        self.assertFalse(scan.accept_removals)
