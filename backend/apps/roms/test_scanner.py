import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.roms.library import FilesystemLibrary, LibraryUnavailable, S3Library
from apps.roms.models import ROM, Playlist, PlaylistItem
from apps.roms.scanner import scan_library
from django.contrib.auth import get_user_model

GUARD = {"guard_ratio": 0.25, "guard_min": 50}


class ScannerTestCase(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.library = FilesystemLibrary(tmp.name, False)

    def touch(self, rel, data=b"x", mtime=None):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if mtime:
            os.utime(path, (mtime, mtime))
        return path

    def scan(self, **kwargs):
        return scan_library(self.library, **{**GUARD, **kwargs})


class ScanLibraryTests(ScannerTestCase):
    def test_first_scan_adds_games(self):
        smw = self.touch("ROMS/SFC/Super Mario World (U).smc", b"12345", mtime=1_700_000_000)
        self.touch("ROMS/SFC/Imgs/Super Mario World (U).png")
        self.touch("ROMS/MD/Sonic.md")
        result = self.scan()
        self.assertEqual(result.added, 2)
        self.assertEqual(len(result.added_ids), 2)
        rom = ROM.objects.get(file="ROMS/SFC/Super Mario World (U).smc")
        self.assertEqual(rom.platform, "SNES")
        self.assertEqual(rom.title, "Super Mario World")
        self.assertEqual(rom.tags, ["USA"])
        self.assertEqual(rom.filename, "Super Mario World (U).smc")
        self.assertEqual(rom.extension, ".smc")
        self.assertEqual(rom.source, "library")
        self.assertIsNone(rom.uploaded_by)
        self.assertEqual(rom.size_bytes, smw.stat().st_size)
        self.assertEqual(rom.modified_at, datetime.fromtimestamp(1_700_000_000, timezone.utc))
        self.assertEqual(rom.cover_path, "ROMS/SFC/Imgs/Super Mario World (U).png")
        self.assertFalse(rom.missing)
        self.assertEqual(ROM.objects.get(file="ROMS/MD/Sonic.md").cover_path, "")

    def test_rescan_unchanged_is_noop(self):
        self.touch("ROMS/SFC/A.smc")
        self.touch("ROMS/SFC/Imgs/A.png")
        self.scan()
        result = self.scan()
        for counter in ("added", "changed", "missing", "restored", "skipped_multifile"):
            self.assertEqual(getattr(result, counter), 0, counter)
        self.assertEqual(result.aborted_reason, "")

    def test_changed_file_updates_size_keeps_row(self):
        self.touch("ROMS/SFC/A.smc", b"1", mtime=1_700_000_000)
        self.scan()
        rom = ROM.objects.get()
        ROM.objects.filter(pk=rom.pk).update(title="My Title")
        user = get_user_model().objects.create_user("u", password="x")
        playlist = Playlist.objects.create(name="p", created_by=user)
        PlaylistItem.objects.create(playlist=playlist, rom=rom, order=0)
        self.touch("ROMS/SFC/A.smc", b"123456", mtime=1_700_000_100)
        result = self.scan()
        self.assertEqual(result.changed, 1)
        again = ROM.objects.get()
        self.assertEqual(again.pk, rom.pk)
        self.assertEqual(again.size_bytes, 6)
        self.assertEqual(again.modified_at, datetime.fromtimestamp(1_700_000_100, timezone.utc))
        self.assertEqual(again.title, "My Title")
        self.assertEqual(playlist.items.count(), 1)

    def test_removed_file_flagged_missing_and_restored(self):
        path = self.touch("ROMS/SFC/A.smc")
        self.touch("ROMS/SFC/B.smc")
        self.scan()
        rom = ROM.objects.get(file="ROMS/SFC/A.smc")
        user = get_user_model().objects.create_user("u", password="x")
        playlist = Playlist.objects.create(name="p", created_by=user)
        PlaylistItem.objects.create(playlist=playlist, rom=rom, order=0)
        path.unlink()
        result = self.scan()
        self.assertEqual(result.missing, 1)
        rom.refresh_from_db()
        self.assertTrue(rom.missing)
        self.assertEqual(playlist.items.count(), 1)
        self.assertEqual(self.scan().missing, 0)
        self.touch("ROMS/SFC/A.smc")
        result = self.scan()
        self.assertEqual(result.restored, 1)
        self.assertEqual(result.added, 0)
        rom.refresh_from_db()
        self.assertFalse(rom.missing)

    def test_guard_aborts_mass_removal(self):
        for i in range(60):
            self.touch(f"ROMS/SFC/g{i:02}.smc")
        self.scan()
        for i in range(20):
            (self.root / f"ROMS/SFC/g{i:02}.smc").unlink()
        result = self.scan()
        self.assertTrue(result.aborted_reason)
        self.assertEqual(result.missing, 0)
        self.assertEqual(ROM.objects.filter(missing=True).count(), 0)
        result = self.scan(accept_removals=True)
        self.assertEqual(result.aborted_reason, "")
        self.assertEqual(result.missing, 20)
        self.assertEqual(ROM.objects.filter(missing=True).count(), 20)

    def test_guard_abort_changes_nothing_else(self):
        for i in range(60):
            self.touch(f"ROMS/SFC/g{i:02}.smc")
        self.scan()
        for i in range(20):
            (self.root / f"ROMS/SFC/g{i:02}.smc").unlink()
        self.touch("ROMS/SFC/new.smc")
        self.touch("ROMS/SFC/g30.smc", b"longer")
        result = self.scan()
        self.assertTrue(result.aborted_reason)
        self.assertEqual((result.added, result.changed), (0, 0))
        self.assertEqual(ROM.objects.count(), 60)
        self.assertEqual(ROM.objects.get(file="ROMS/SFC/g30.smc").size_bytes, 1)

    def test_guard_ignored_below_min(self):
        for name in "abc":
            self.touch(f"ROMS/SFC/{name}.smc")
        self.scan()
        (self.root / "ROMS/SFC/a.smc").unlink()
        (self.root / "ROMS/SFC/b.smc").unlink()
        result = self.scan()
        self.assertEqual(result.aborted_reason, "")
        self.assertEqual(result.missing, 2)

    def test_old_upload_rows_count_as_missing(self):
        ROM.objects.create(title="Old", file="roms/old.sfc", source="upload")
        self.touch("ROMS/SFC/A.smc")
        result = self.scan()
        self.assertEqual(result.missing, 1)
        self.assertTrue(ROM.objects.get(file="roms/old.sfc").missing)

    def test_unreachable_root_aborts_without_changes(self):
        self.touch("ROMS/SFC/A.smc")
        self.scan()
        library = FilesystemLibrary(str(self.root / "gone"), False)
        result = scan_library(library, **GUARD)
        self.assertTrue(result.aborted_reason)
        self.assertEqual(ROM.objects.filter(missing=True).count(), 0)

    def test_empty_systems_folder_aborts_without_changes(self):
        self.touch("ROMS/SFC/A.smc")
        self.scan()
        (self.root / "ROMS/SFC/A.smc").unlink()
        (self.root / "ROMS/SFC").rmdir()
        result = self.scan()
        self.assertTrue(result.aborted_reason)
        self.assertEqual(ROM.objects.filter(missing=True).count(), 0)

    def test_unknown_and_non_game_folders(self):
        self.touch("ROMS/WEIRD/x.smc")
        self.touch("ROMS/PORTS/a.sh")
        self.touch("ROMS/DREAMCAST/Sonic Adventure/track.bin")
        self.touch("ROMS/SFC/A.smc")
        result = self.scan()
        self.assertEqual(result.unknown_folders, ["WEIRD"])
        self.assertEqual(result.added, 1)
        self.assertEqual(result.skipped_other, 1)

    def test_multifile_sets_skipped(self):
        self.touch("ROMS/PS/Game.cue")
        self.touch("ROMS/PS/Game (Track 1).bin")
        result = self.scan()
        self.assertEqual(result.skipped_multifile, 2)
        self.assertEqual(result.added, 0)
        self.assertEqual(ROM.objects.count(), 0)

    def test_bin_without_cue_is_a_game(self):
        self.touch("ROMS/MD/Sonic.bin")
        self.assertEqual(self.scan().added, 1)

    def test_alias_folders_share_platform(self):
        self.touch("ROMS/SFC/Game.smc")
        self.touch("ROMS/snes/Game.smc")
        result = self.scan()
        self.assertEqual(result.added, 2)
        self.assertEqual(set(ROM.objects.values_list("platform", flat=True)), {"SNES"})

    def test_uppercase_extensions_and_cover_match(self):
        self.touch("ROMS/PS/Game.PBP")
        self.touch("ROMS/PS/imgs/Game.PNG")
        result = self.scan()
        self.assertEqual(result.added, 1)
        self.assertEqual(ROM.objects.get().cover_path, "ROMS/PS/imgs/Game.PNG")

    def test_odd_names_round_trip(self):
        names = [
            "Tony Hawk's Underground 2 (USA, Europe).gba",
            "Pokémon - Edición Esmeralda (Spain).gba",
            "Lilo & Stitch.gba",
        ]
        for name in names:
            self.touch(f"ROMS/GBA/{name}")
        self.assertEqual(self.scan().added, 3)
        for name in names:
            rom = ROM.objects.get(file=f"ROMS/GBA/{name}")
            self.assertEqual(rom.file.name, f"ROMS/GBA/{name}")
            self.assertEqual(rom.filename, name)

    def test_cover_appears_later_is_linked(self):
        self.touch("ROMS/SFC/A.smc")
        self.scan()
        self.touch("ROMS/SFC/Imgs/A.png")
        result = self.scan()
        self.assertEqual(result.changed, 1)
        self.assertEqual(ROM.objects.get().cover_path, "ROMS/SFC/Imgs/A.png")

    def test_ngp_split(self):
        self.touch("ROMS/NGP/a.ngc")
        self.scan()
        self.assertEqual(ROM.objects.get().platform, "Neo Geo Pocket Color")

    def test_ignores_litter(self):
        self.touch("ROMS/SFC/._x.smc")
        self.touch("ROMS/SFC/.DS_Store")
        self.touch("ROMS/SFC/x.txt")
        result = self.scan()
        self.assertEqual(result.added, 0)
        self.assertEqual(result.skipped_other, 1)

    def test_writes_in_batches(self):
        for i in range(1100):
            self.touch(f"ROMS/GBA/g{i}.gba")
        self.assertEqual(self.scan().added, 1100)
        for i in range(1100):
            self.touch(f"ROMS/GBA/g{i}.gba", b"yy")
        with CaptureQueriesContext(connection) as queries:
            result = self.scan()
        self.assertEqual(result.changed, 1100)
        self.assertLess(len(queries), 15)


class BrokenObjects:
    def filter(self, Prefix):
        raise RuntimeError("AccessDenied")


class BrokenBucketStorage:
    def __init__(self):
        self.bucket = self
        self.objects = BrokenObjects()


class FailingMidwayLibrary(FilesystemLibrary):
    def entries(self):
        for entry in super().entries():
            yield entry
            break
        raise LibraryUnavailable("share went away")


class ScanEdgeTests(ScannerTestCase):
    def games(self, count, folder="SFC"):
        for i in range(count):
            self.touch(f"ROMS/{folder}/g{i:02}.smc")

    def remove(self, count, folder="SFC"):
        for i in range(count):
            (self.root / f"ROMS/{folder}/g{i:02}.smc").unlink()

    def test_unreachable_s3_aborts_without_changes(self):
        ROM.objects.create(title="A", file="ROMS/SFC/A.smc", source="library")
        result = scan_library(S3Library(BrokenBucketStorage(), "", False), **GUARD)
        self.assertIn("AccessDenied", result.aborted_reason)
        self.assertFalse(ROM.objects.get().missing)

    def test_failure_mid_listing_aborts_without_writes(self):
        self.games(3)
        self.scan()
        self.touch("ROMS/SFC/new.smc")
        (self.root / "ROMS/SFC/g00.smc").unlink()
        library = FailingMidwayLibrary(str(self.root), False)
        result = scan_library(library, **GUARD)
        self.assertTrue(result.aborted_reason)
        self.assertEqual(ROM.objects.count(), 3)
        self.assertEqual(ROM.objects.filter(missing=True).count(), 0)

    def test_exactly_at_ratio_does_not_abort(self):
        self.games(60)
        self.scan()
        self.remove(15)
        result = self.scan()
        self.assertEqual(result.aborted_reason, "")
        self.assertEqual(result.missing, 15)

    def test_present_equal_to_min_applies_guard(self):
        self.games(50)
        self.scan()
        self.remove(13)
        result = self.scan()
        self.assertTrue(result.aborted_reason)
        self.assertEqual(ROM.objects.filter(missing=True).count(), 0)

    def test_guard_base_excludes_already_missing_rows(self):
        self.games(100)
        self.scan()
        self.remove(50)
        self.scan(accept_removals=True)
        self.assertEqual(ROM.objects.filter(missing=True).count(), 50)
        # 50 present now: removing 13 is 26% of present (but only 13% of all rows).
        for i in range(50, 63):
            (self.root / f"ROMS/SFC/g{i:02}.smc").unlink()
        result = self.scan()
        self.assertTrue(result.aborted_reason)

    def test_restored_row_gets_new_size_and_mtime_counted_once(self):
        path = self.touch("ROMS/SFC/A.smc", b"1", mtime=1_700_000_000)
        self.touch("ROMS/SFC/B.smc")
        self.scan()
        path.unlink()
        self.assertEqual(self.scan().missing, 1)
        self.touch("ROMS/SFC/A.smc", b"123456", mtime=1_700_000_500)
        result = self.scan()
        self.assertEqual((result.restored, result.changed), (1, 0))
        rom = ROM.objects.get(file="ROMS/SFC/A.smc")
        self.assertFalse(rom.missing)
        self.assertEqual(rom.size_bytes, 6)
        self.assertEqual(rom.modified_at, datetime.fromtimestamp(1_700_000_500, timezone.utc))

    def test_cover_disappears_is_cleared(self):
        self.touch("ROMS/SFC/A.smc")
        cover = self.touch("ROMS/SFC/Imgs/A.png")
        self.scan()
        cover.unlink()
        result = self.scan()
        self.assertEqual(result.changed, 1)
        self.assertEqual(ROM.objects.get().cover_path, "")

    def test_listing_without_games_aborts_when_rows_present(self):
        listings = {
            "only covers": ["ROMS/SFC/Imgs/A.png"],
            "only non-game": ["ROMS/PORTS/a.sh"],
            "only unknown": ["ROMS/WEIRD/x.smc"],
        }
        for label, files in listings.items():
            with self.subTest(label):
                ROM.objects.all().delete()
                shutil.rmtree(self.root / "ROMS", ignore_errors=True)
                self.touch("ROMS/SFC/A.smc")
                self.scan()
                (self.root / "ROMS/SFC/A.smc").unlink()
                for rel in files:
                    self.touch(rel)
                result = self.scan()
                self.assertTrue(result.aborted_reason)
                self.assertEqual(ROM.objects.filter(missing=True).count(), 0)
                result = self.scan(accept_removals=True)
                self.assertEqual(result.missing, 1)

    def test_listing_without_games_and_no_rows_is_fine(self):
        self.touch("ROMS/PORTS/a.sh")
        result = self.scan()
        self.assertEqual(result.aborted_reason, "")
