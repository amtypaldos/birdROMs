import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.test import SimpleTestCase

from apps.roms.library import (
    FilesystemLibrary,
    LibraryEntry,
    LibraryUnavailable,
    S3Library,
)
from birdroms.library_config import LibrarySettings, parse_library_settings


class ParseLibrarySettingsTests(SimpleTestCase):
    def test_defaults(self):
        self.assertEqual(
            parse_library_settings({}),
            LibrarySettings(
                backend="filesystem",
                root="/library",
                s3_prefix="",
                read_only=False,
                write_covers=True,
                scan_crontab="*/15 * * * *",
                guard_ratio=0.25,
                guard_min=50,
            ),
        )

    def test_overrides(self):
        settings = parse_library_settings(
            {
                "LIBRARY_BACKEND": " S3 ",
                "LIBRARY_ROOT": "/mnt/nas",
                "LIBRARY_S3_PREFIX": "roms",
                "LIBRARY_READ_ONLY": "true",
                "LIBRARY_WRITE_COVERS": "false",
                "LIBRARY_SCAN_CRONTAB": "0 * * * *",
                "LIBRARY_MISSING_GUARD_RATIO": "0.5",
                "LIBRARY_MISSING_GUARD_MIN": "10",
            }
        )
        self.assertEqual(settings.backend, "s3")
        self.assertEqual(settings.root, "/mnt/nas")
        self.assertEqual(settings.s3_prefix, "roms")
        self.assertTrue(settings.read_only)
        self.assertFalse(settings.write_covers)
        self.assertEqual(settings.scan_crontab, "0 * * * *")
        self.assertEqual(settings.guard_ratio, 0.5)
        self.assertEqual(settings.guard_min, 10)

    def test_unknown_backend_raises(self):
        with self.assertRaises(ValueError):
            parse_library_settings({"LIBRARY_BACKEND": "ftp"})


class FilesystemLibraryTests(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def touch(self, rel, data=b"x"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_systems_folder_detection(self):
        for folder, expected in (("ROMS", "ROMS"), ("Roms", "Roms"), (None, "")):
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                (base / (folder or "SFC")).mkdir()
                if folder:
                    (base / folder / "SFC").mkdir()
                self.assertEqual(FilesystemLibrary(tmp, False).systems_prefix, expected)

    def test_entries_lists_files_and_imgs(self):
        rom = self.touch("ROMS/SFC/Game.sfc", b"abcd")
        self.touch("ROMS/SFC/Imgs/Game.png", b"pp")
        self.touch("ROMS/MD/imgs/Other.PNG", b"p")
        self.touch("ROMS/SFC/deeper/Nope.sfc")
        self.touch("ROMS/SFC/Imgs/deep/Nope.png")
        self.touch("ROMS/SFC/._Game.sfc")
        self.touch("ROMS/SFC/.hidden")
        self.touch("ROMS/SFC/Imgs/._Game.png")
        self.touch("ROMS/stray.txt")
        os.utime(rom, (1_700_000_000, 1_700_000_000))

        entries = {e.path: e for e in FilesystemLibrary(str(self.root), False).entries()}

        self.assertEqual(
            set(entries),
            {"ROMS/SFC/Game.sfc", "ROMS/SFC/Imgs/Game.png", "ROMS/MD/imgs/Other.PNG"},
        )
        game = entries["ROMS/SFC/Game.sfc"]
        self.assertEqual(game.size, 4)
        self.assertEqual(game.modified, datetime.fromtimestamp(1_700_000_000, timezone.utc))
        self.assertEqual(game.modified.utcoffset(), timedelta(0))
        self.assertIsInstance(game, LibraryEntry)

    def test_entries_report_skipped_subfolders(self):
        self.touch("ROMS/DC/Sonic/track.bin")
        self.touch("ROMS/DC/Sonic/more.bin")
        self.touch("ROMS/DC/Other/a.bin")
        self.touch("ROMS/DC/Imgs/a.png")
        self.touch("ROMS/DC/.hidden/a.bin")
        library = FilesystemLibrary(str(self.root), False)
        list(library.entries())
        self.assertEqual(library.subfolders, {"DC": 2})

    def test_entries_without_systems_folder(self):
        self.touch("SFC/Game.sfc")
        paths = [e.path for e in FilesystemLibrary(str(self.root), False).entries()]
        self.assertEqual(paths, ["SFC/Game.sfc"])

    def test_missing_root_is_unavailable(self):
        library = FilesystemLibrary(str(self.root / "gone"), False)
        with self.assertRaises(LibraryUnavailable):
            list(library.entries())

    def test_write_new_creates_parents_and_refuses_existing(self):
        library = FilesystemLibrary(str(self.root), False)
        library.write_new("ROMS/SFC/Imgs/A.png", b"data")
        self.assertEqual((self.root / "ROMS/SFC/Imgs/A.png").read_bytes(), b"data")
        self.assertTrue(library.exists("ROMS/SFC/Imgs/A.png"))
        with self.assertRaises(FileExistsError):
            library.write_new("ROMS/SFC/Imgs/A.png", b"other")
        self.assertEqual((self.root / "ROMS/SFC/Imgs/A.png").read_bytes(), b"data")

    def test_read_only_refuses_writes(self):
        library = FilesystemLibrary(str(self.root), True)
        self.assertFalse(library.writable)
        with self.assertRaises(PermissionError):
            library.write_new("ROMS/SFC/A.sfc", b"x")
        self.assertFalse((self.root / "ROMS").exists())

    def test_writable_follows_os_access(self):
        self.assertTrue(FilesystemLibrary(str(self.root), False).writable)
        self.assertFalse(FilesystemLibrary(str(self.root / "gone"), False).writable)
        self.root.chmod(0o500)
        self.addCleanup(self.root.chmod, 0o700)
        if not os.access(self.root, os.W_OK):  # root user can write anyway
            self.assertFalse(FilesystemLibrary(str(self.root), False).writable)

    def test_storage_is_rooted_at_library(self):
        self.touch("ROMS/SFC/Game.sfc", b"abcd")
        storage = FilesystemLibrary(str(self.root), False).storage
        self.assertEqual(Path(storage.path("ROMS/SFC/Game.sfc")), self.root / "ROMS/SFC/Game.sfc")


class FakeObject:
    def __init__(self, key, size, last_modified):
        self.key = key
        self.size = size
        self.last_modified = last_modified


class FakeObjects:
    def __init__(self, objects):
        self.objects = objects
        self.prefixes = []

    def filter(self, Prefix):
        self.prefixes.append(Prefix)
        return [o for o in self.objects if o.key.startswith(Prefix)]


class FakeStorage:
    def __init__(self, objects, keys=()):
        self.objects = FakeObjects(objects)
        self.bucket = self
        self.keys = set(keys)
        self.saved = []

    def exists(self, name):
        return name in self.keys

    def save(self, name, content):
        self.saved.append((name, content.read()))
        self.keys.add(name)
        return name


class S3LibraryTests(SimpleTestCase):
    def when(self, hour):
        return datetime(2026, 1, 1, hour, tzinfo=timezone.utc)

    def test_entries_strip_prefix_and_filter_layout(self):
        storage = FakeStorage(
            [
                FakeObject("lib/ROMS/", 0, self.when(1)),
                FakeObject("lib/ROMS/SFC/Game.sfc", 10, self.when(2)),
                FakeObject("lib/ROMS/SFC/Imgs/Game.png", 5, self.when(3)),
                FakeObject("lib/ROMS/SFC/deep/x/Nope.sfc", 1, self.when(4)),
                FakeObject("lib/ROMS/SFC/._Game.sfc", 1, self.when(4)),
                FakeObject("lib/ROMS/stray.txt", 1, self.when(4)),
                FakeObject("other/ROMS/SFC/Else.sfc", 1, self.when(4)),
            ]
        )
        library = S3Library(storage, "lib", False)
        entries = {e.path: e for e in library.entries()}
        self.assertEqual(set(entries), {"ROMS/SFC/Game.sfc", "ROMS/SFC/Imgs/Game.png"})
        self.assertEqual(entries["ROMS/SFC/Game.sfc"].size, 10)
        self.assertEqual(entries["ROMS/SFC/Game.sfc"].modified, self.when(2))
        self.assertEqual(library.systems_prefix, "ROMS")
        self.assertEqual(storage.objects.prefixes[0], "lib/")

    def test_entries_report_skipped_subfolders(self):
        storage = FakeStorage(
            [
                FakeObject("ROMS/DC/Sonic/track.bin", 1, self.when(1)),
                FakeObject("ROMS/DC/Sonic/more.bin", 1, self.when(1)),
                FakeObject("ROMS/DC/Other/a.bin", 1, self.when(1)),
                FakeObject("ROMS/DC/Imgs/a.png", 1, self.when(1)),
                FakeObject("ROMS/DC/Imgs/deep/a.png", 1, self.when(1)),
                FakeObject("ROMS/DC/Game.cue", 1, self.when(1)),
            ]
        )
        library = S3Library(storage, "", False)
        list(library.entries())
        self.assertEqual(library.subfolders, {"DC": 2})

    def test_empty_prefix_and_root_systems(self):
        storage = FakeStorage([FakeObject("SFC/Game.sfc", 1, self.when(1))])
        library = S3Library(storage, "", False)
        self.assertEqual([e.path for e in library.entries()], ["SFC/Game.sfc"])
        self.assertEqual(library.systems_prefix, "")

    def test_empty_bucket_is_unavailable(self):
        library = S3Library(FakeStorage([]), "lib", False)
        with self.assertRaises(LibraryUnavailable):
            list(library.entries())

    def test_write_new_refuses_existing_and_read_only(self):
        storage = FakeStorage([], keys={"ROMS/SFC/Imgs/A.png"})
        library = S3Library(storage, "", False)
        with self.assertRaises(FileExistsError):
            library.write_new("ROMS/SFC/Imgs/A.png", b"x")
        library.write_new("ROMS/SFC/Imgs/B.png", b"y")
        self.assertEqual(storage.saved, [("ROMS/SFC/Imgs/B.png", b"y")])
        ro = S3Library(storage, "", True)
        self.assertFalse(ro.writable)
        with self.assertRaises(PermissionError):
            ro.write_new("ROMS/SFC/C.sfc", b"z")
