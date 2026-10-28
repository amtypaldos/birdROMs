import shutil
import tempfile
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.roms.library import FilesystemLibrary, LibraryUnavailable
from apps.roms.models import ROM, LibraryScan, Playlist, PlaylistItem
from apps.roms.scanner import run_library_scan
from apps.roms.tests import empty_library_root, make_user
from birdroms.tasks import roms_missing_cover_art

PNG = b"\x89PNG\r\n\x1a\nlibrary-cover"


class LibraryRootTestCase(APITestCase):
    """Starts each test with an empty library (the shared temp root) that has a `ROMS` folder."""

    def setUp(self):
        empty_library_root()
        self.root = Path(settings.LIBRARY.root)
        self.admin = make_user("admin", "super_admin")
        self.reader = make_user("reader", "readonly")

    def put(self, rel, data=b"rom-bytes"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def library_rom(self, rel="ROMS/SFC/Game (USA).smc", **kwargs):
        self.put(rel)
        defaults = {"title": "Game", "file": rel, "source": "library", "filename": Path(rel).name}
        return ROM.objects.create(**{**defaults, **kwargs})


class HideMissingTests(LibraryRootTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.reader)
        self.present = self.library_rom("ROMS/SFC/Present.smc", title="Present")
        self.gone = self.library_rom("ROMS/GBA/Gone.gba", title="Gone", missing=True, platform="Game Boy Advance")

    def ids(self, response):
        return [row["id"] for row in response.data["results"]]

    def test_list_excludes_missing(self):
        self.assertEqual(self.ids(self.client.get(reverse("rom-list"))), [self.present.pk])

    def test_device_list_excludes_missing(self):
        self.assertEqual(self.ids(self.client.get(reverse("rom-list"), {"fields": "device"})), [self.present.pk])

    def test_platforms_exclude_platform_with_only_missing_roms(self):
        self.assertEqual(self.client.get(reverse("rom-platforms")).data, ["SNES"])

    def test_download_and_cover_of_missing_rom_are_404(self):
        self.gone.cover_path = "ROMS/GBA/Imgs/Gone.png"
        self.gone.save()
        self.put("ROMS/GBA/Imgs/Gone.png", PNG)
        self.assertEqual(self.client.get(reverse("rom-download", args=[self.gone.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("rom-cover", args=[self.gone.pk])).status_code, 404)

    def test_playlist_hides_missing_roms_and_counts(self):
        playlist = Playlist.objects.create(name="Mix", created_by=self.admin)
        PlaylistItem.objects.create(playlist=playlist, rom=self.present, order=0)
        PlaylistItem.objects.create(playlist=playlist, rom=self.gone, order=1)
        detail = self.client.get(reverse("playlist-detail", args=[playlist.pk])).data
        self.assertEqual([r["id"] for r in detail["roms"]], [self.present.pk])
        self.assertEqual(detail["rom_count"], 1)
        listing = self.client.get(reverse("playlist-list")).data
        rows = listing["results"] if isinstance(listing, dict) else listing
        self.assertEqual(rows[0]["rom_count"], 1)

    def test_playlist_write_rejects_missing_rom_ids(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            reverse("playlist-list"), {"name": "X", "rom_ids": [self.gone.pk]}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(f"Unknown ROM id(s): {self.gone.pk}.", str(response.data))


    def test_replacing_rom_ids_keeps_hidden_items_after_the_visible_ones(self):
        other = self.library_rom("ROMS/SFC/Other.smc", title="Other")
        playlist = Playlist.objects.create(name="Mix", created_by=self.admin)
        for order, rom in enumerate((self.present, self.gone, other)):
            PlaylistItem.objects.create(playlist=playlist, rom=rom, order=order)
        self.client.force_authenticate(self.admin)
        url = reverse("playlist-detail", args=[playlist.pk])
        response = self.client.patch(url, {"rom_ids": [other.pk, self.present.pk]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([r["id"] for r in response.data["roms"]], [other.pk, self.present.pk])
        self.assertEqual(
            list(playlist.items.values_list("rom_id", flat=True)), [other.pk, self.present.pk, self.gone.pk]
        )
        ROM.objects.filter(pk=self.gone.pk).update(missing=False)  # its file came back
        detail = self.client.get(url).data
        self.assertEqual([r["id"] for r in detail["roms"]], [other.pk, self.present.pk, self.gone.pk])


    def test_replacing_with_a_rom_that_just_went_missing_lists_it_once(self):
        from apps.roms.serializers import PlaylistSerializer

        playlist = Playlist.objects.create(name="Mix", created_by=self.admin)
        PlaylistItem.objects.create(playlist=playlist, rom=self.gone, order=0)
        PlaylistSerializer()._set_items(playlist, [self.present, self.gone])  # validated before it vanished
        self.assertEqual(list(playlist.items.values_list("rom_id", flat=True)), [self.present.pk, self.gone.pk])


class LibraryDownloadAndCoverTests(LibraryRootTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.reader)

    def test_download_uses_exact_library_name(self):
        name = "Tony Hawk's Underground 2 (USA, Europe).gba"
        rom = self.library_rom(f"ROMS/GBA/{name}", title="Tony Hawk's Underground 2")
        response = self.client.get(reverse("rom-download", args=[rom.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"rom-bytes")
        self.assertIn(f"filename=\"{name}\"", response["Content-Disposition"])

    def test_cover_endpoint_serves_library_png(self):
        rom = self.library_rom(cover_path="ROMS/SFC/Imgs/Game (USA).png")
        self.put("ROMS/SFC/Imgs/Game (USA).png", PNG)
        response = self.client.get(reverse("rom-cover", args=[rom.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(b"".join(response.streaming_content), PNG)

    def test_cover_falls_back_to_stored_art_when_library_png_is_gone(self):
        rom = self.library_rom(cover_path="ROMS/SFC/Imgs/Gone.png")
        rom.cover_art.save("stored.png", ContentFile(PNG), save=True)
        response = self.client.get(reverse("rom-cover", args=[rom.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PNG)

    def test_cover_missing_from_library_is_404(self):
        rom = self.library_rom(cover_path="ROMS/SFC/Imgs/Nope.png")
        self.assertEqual(self.client.get(reverse("rom-cover", args=[rom.pk])).status_code, 404)

    def test_cover_urls_exposed_for_library_covers(self):
        rom = self.library_rom(cover_path="ROMS/SFC/Imgs/Game (USA).png")
        row = self.client.get(reverse("rom-list")).data["results"][0]
        self.assertTrue(row["cover_art_url"].endswith(f"/api/roms/{rom.pk}/cover/"))
        device = self.client.get(reverse("rom-list"), {"fields": "device"}).data["results"][0]
        self.assertTrue(device["cover_url"].endswith(f"/api/roms/{rom.pk}/cover/"))

    def test_device_size_comes_from_stored_value_without_touching_storage(self):
        self.library_rom(size_bytes=1234)
        with mock.patch(
            "django.db.models.fields.files.FieldFile.size", new_callable=mock.PropertyMock, side_effect=OSError
        ):
            row = self.client.get(reverse("rom-list"), {"fields": "device"}).data["results"][0]
        self.assertEqual(row["size_bytes"], 1234)

    def test_library_rom_listed_with_null_uploader(self):
        self.library_rom()
        row = self.client.get(reverse("rom-list")).data["results"][0]
        self.assertIsNone(row["uploaded_by_username"])

    def test_sweep_filter_skips_library_covers_and_missing(self):
        covered = self.library_rom("ROMS/SFC/A.smc", cover_path="ROMS/SFC/Imgs/A.png")
        gone = self.library_rom("ROMS/SFC/B.smc", missing=True)
        bare = self.library_rom("ROMS/SFC/C.smc")
        self.assertEqual(list(roms_missing_cover_art()), [bare])
        self.assertNotIn(covered, roms_missing_cover_art())
        self.assertNotIn(gone, roms_missing_cover_art())


class LibraryUploadTests(LibraryRootTestCase):
    url = reverse("rom-list")

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin)

    def upload(self, name, data=b"smc-bytes", **extra):
        return self.client.post(
            self.url, {"file": SimpleUploadedFile(name, data), **extra}, format="multipart"
        )

    def test_upload_with_platform_lands_in_its_muos_folder(self):
        response = self.upload("Super Mario World (U).smc", platform="SNES")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((self.root / "ROMS/SFC/Super Mario World (U).smc").read_bytes(), b"smc-bytes")
        rom = ROM.objects.get()
        self.assertEqual(rom.file.name, "ROMS/SFC/Super Mario World (U).smc")
        self.assertEqual(rom.source, "upload")
        self.assertEqual(rom.size_bytes, len(b"smc-bytes"))
        self.assertIsNotNone(rom.modified_at)
        self.assertEqual(rom.uploaded_by, self.admin)
        self.assertEqual(rom.filename, "Super Mario World (U).smc")

    def test_upload_without_platform_uses_extension_classification(self):
        self.assertEqual(self.upload("Sonic.md").status_code, 201)
        self.assertTrue((self.root / "ROMS/MD/Sonic.md").exists())

    def test_archive_platform_goes_to_unsorted(self):
        self.assertEqual(self.upload("Bundle.zip", platform="Archive").status_code, 201)
        self.assertTrue((self.root / "ROMS/_UNSORTED/Bundle.zip").exists())

    def test_library_without_systems_folder_writes_folder_at_root(self):
        shutil.rmtree(self.root / "ROMS")
        self.assertEqual(self.upload("Sonic.md").status_code, 201)
        self.assertEqual(ROM.objects.get().file.name, "MD/Sonic.md")

    def test_upload_refuses_existing_file(self):
        self.put("ROMS/SFC/Game.smc", b"original")
        response = self.upload("Game.smc", b"replacement", platform="SNES")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["file"][0], "Game.smc is already in the library.")
        self.assertEqual((self.root / "ROMS/SFC/Game.smc").read_bytes(), b"original")
        self.assertEqual(ROM.objects.count(), 0)

    def test_upload_over_missing_row_restores_it(self):
        gone = self.library_rom("ROMS/SFC/Game.smc", missing=True)
        (self.root / "ROMS/SFC/Game.smc").unlink()
        response = self.upload("Game.smc", b"new", platform="SNES")
        self.assertEqual(response.status_code, 201, response.data)
        old_uploaded_at = gone.uploaded_at
        gone.refresh_from_db()
        self.assertFalse(gone.missing)
        self.assertEqual(ROM.objects.count(), 1)
        self.assertEqual(response.data["id"], gone.pk)
        self.assertEqual(gone.source, "upload")
        self.assertEqual(gone.uploaded_by, self.admin)
        self.assertEqual(gone.size_bytes, 3)
        self.assertEqual(gone.title, "Game")
        self.assertGreater(gone.uploaded_at, old_uploaded_at)
        self.assertEqual((self.root / "ROMS/SFC/Game.smc").read_bytes(), b"new")

    def test_upload_over_present_row_whose_file_vanished_restores_it(self):
        stale = self.library_rom("ROMS/SFC/Game.smc")  # missing=False, scan hasn't noticed yet
        (self.root / "ROMS/SFC/Game.smc").unlink()
        response = self.upload("Game.smc", b"new", platform="SNES")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(ROM.objects.count(), 1)
        stale.refresh_from_db()
        self.assertEqual(stale.source, "upload")
        self.assertEqual(stale.uploaded_by, self.admin)
        self.assertEqual((self.root / "ROMS/SFC/Game.smc").read_bytes(), b"new")

    def test_upload_streams_a_file_not_bytes_into_the_library(self):
        from django.core.files.base import File

        seen = []
        real = FilesystemLibrary.write_new

        def spy(library, path, content):
            seen.append(content)
            return real(library, path, content)

        with mock.patch.object(FilesystemLibrary, "write_new", spy):
            self.assertEqual(self.upload("Game.smc", b"streamed", platform="SNES").status_code, 201)
        self.assertIsInstance(seen[0], File)
        self.assertEqual((self.root / "ROMS/SFC/Game.smc").read_bytes(), b"streamed")

    def test_upload_refused_when_read_only(self):
        with self.settings(LIBRARY=settings.LIBRARY.__class__(**{**settings.LIBRARY.__dict__, "read_only": True})):
            response = self.upload("Game.smc", platform="SNES")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["file"][0], "Uploads are disabled: the ROM library is read-only.")
        self.assertEqual(ROM.objects.count(), 0)
        self.assertFalse((self.root / "ROMS/SFC").exists())

    def test_upload_when_library_unavailable(self):
        with mock.patch("apps.roms.library.FilesystemLibrary.write_new", side_effect=LibraryUnavailable("down")):
            response = self.upload("Game.smc", platform="SNES")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["file"][0], "The ROM library is unavailable.")
        self.assertEqual(ROM.objects.count(), 0)

    def test_upload_to_missing_library_root_is_unavailable(self):
        gone = str(self.root / "gone")
        with self.settings(LIBRARY=settings.LIBRARY.__class__(**{**settings.LIBRARY.__dict__, "root": gone})):
            response = self.upload("Game.smc", platform="SNES")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["file"][0], "The ROM library is unavailable.")

    def test_upload_reuses_an_existing_folder_of_the_platform(self):
        (self.root / "ROMS/snes").mkdir()
        self.assertEqual(self.upload("Game.smc", platform="SNES").status_code, 201)
        self.assertEqual(ROM.objects.get().file.name, "ROMS/snes/Game.smc")
        self.assertTrue((self.root / "ROMS/snes/Game.smc").exists())

    def test_upload_reuses_a_lower_case_muos_folder(self):
        (self.root / "ROMS/sfc").mkdir()
        self.assertEqual(self.upload("Game.smc", platform="SNES").status_code, 201)
        self.assertEqual(ROM.objects.get().file.name, "ROMS/sfc/Game.smc")

    def test_upload_prefers_the_muos_folder_over_an_alias(self):
        (self.root / "ROMS/snes").mkdir()
        (self.root / "ROMS/SFC").mkdir()
        self.assertEqual(self.upload("Game.smc", platform="SNES").status_code, 201)
        self.assertEqual(ROM.objects.get().file.name, "ROMS/SFC/Game.smc")

    def test_upload_records_the_written_files_mtime(self):
        self.assertEqual(self.upload("Game.smc", platform="SNES").status_code, 201)
        mtime = (self.root / "ROMS/SFC/Game.smc").stat().st_mtime
        self.assertEqual(ROM.objects.get().modified_at, datetime.fromtimestamp(mtime, dt_timezone.utc))
        with mock.patch("birdroms.tasks.scrape_rom_cover"):
            scan = run_library_scan()
        self.assertEqual((scan.state, scan.changed, scan.added), ("ok", 0, 0))

    def test_update_refuses_a_new_file(self):
        self.upload("Game.smc", b"original", platform="SNES")
        rom = ROM.objects.get()
        url = reverse("rom-detail", args=[rom.pk])
        for method in (self.client.patch, self.client.put):
            with self.subTest(method=method.__name__):
                response = method(
                    url,
                    {"title": "T", "file": SimpleUploadedFile("Other.smc", b"replacement")},
                    format="multipart",
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["file"][0], "A ROM's file can't be replaced; upload it as a new file.")
        rom.refresh_from_db()
        self.assertEqual(rom.file.name, "ROMS/SFC/Game.smc")
        self.assertEqual((self.root / "ROMS/SFC/Game.smc").read_bytes(), b"original")
        self.assertFalse((self.root / "ROMS/SFC/Other.smc").exists())

    def test_update_without_a_file_still_works(self):
        self.upload("Game.smc", platform="SNES")
        rom = ROM.objects.get()
        response = self.client.patch(reverse("rom-detail", args=[rom.pk]), {"title": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        rom.refresh_from_db()
        self.assertEqual(rom.title, "Renamed")


class UploadThenScanTests(LibraryRootTestCase):
    """Uploads must survive the next scan, wherever they landed."""

    def test_uploads_stay_visible_after_a_scan(self):
        self.client.force_authenticate(self.admin)
        uploads = {"Game.chd": {}, "Disc.cue": {}, "Bundle.zip": {}, "Game (USA).sfc": {"platform": "SNES"}}
        with mock.patch("apps.roms.views.scrape_rom_cover"):
            for name, extra in uploads.items():
                data = f"bytes of {name}".encode()
                response = self.client.post(
                    reverse("rom-list"), {"file": SimpleUploadedFile(name, data), **extra}, format="multipart"
                )
                self.assertEqual(response.status_code, 201, response.data)
        sizes = dict(ROM.objects.values_list("filename", "size_bytes"))
        with mock.patch("birdroms.tasks.scrape_rom_cover"):
            scan = run_library_scan()
        self.assertEqual(scan.state, "ok", scan.message)
        self.assertEqual((scan.missing, scan.added), (0, 0))
        self.assertNotIn("_UNSORTED", scan.unknown_folders)
        self.assertEqual(ROM.objects.filter(missing=False).count(), 4)
        self.assertEqual(dict(ROM.objects.values_list("filename", "size_bytes")), sizes)
        self.assertEqual(sizes, {name: len(f"bytes of {name}".encode()) for name in uploads})
        self.assertEqual(ROM.objects.get(filename="Game (USA).sfc").file.name, "ROMS/SFC/Game (USA).sfc")
        self.assertEqual(ROM.objects.get(filename="Disc.cue").file.name, "ROMS/_UNSORTED/Disc.cue")


class LibraryStatusTests(LibraryRootTestCase):
    status_url = reverse("library-status")
    scan_url = reverse("library-scan")

    def test_non_admins_get_403(self):
        for user in (self.reader, make_user("nobody")):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.status_url).status_code, 403)
            self.assertEqual(self.client.post(self.scan_url, {}, format="json").status_code, 403)

    def test_anonymous_is_refused(self):
        self.assertIn(self.client.get(self.status_url).status_code, (401, 403))

    def test_status_without_scans(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.status_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"backend": "filesystem", "writable": True, "write_covers": True, "running": False, "last_scan": None},
        )

    def test_status_reports_last_scan(self):
        self.client.force_authenticate(self.admin)
        LibraryScan.objects.create(state="ok", added=3, unknown_folders=["FOO"], finished_at=timezone.now())
        latest = LibraryScan.objects.create(
            state="aborted", added=1, missing=7, message="too many", finished_at=timezone.now()
        )
        data = self.client.get(self.status_url).data
        self.assertEqual(
            set(data["last_scan"]),
            {
                "state", "started_at", "finished_at", "added", "changed", "missing", "restored",
                "skipped_multifile", "skipped_other", "unknown_folders", "message",
            },
        )
        self.assertEqual(data["last_scan"]["state"], latest.state)
        self.assertEqual(data["last_scan"]["missing"], 7)
        self.assertEqual(data["last_scan"]["message"], "too many")
        self.assertFalse(data["running"])

    def test_running_means_recent_running_row(self):
        self.client.force_authenticate(self.admin)
        scan = LibraryScan.objects.create(state="running")
        self.assertTrue(self.client.get(self.status_url).data["running"])
        LibraryScan.objects.filter(pk=scan.pk).update(started_at=timezone.now() - timedelta(hours=7))
        self.assertFalse(self.client.get(self.status_url).data["running"])

    def test_scan_enqueues_task(self):
        self.client.force_authenticate(self.admin)
        with mock.patch("apps.roms.library_views.scan_library_task") as task:
            response = self.client.post(self.scan_url, {"accept_removals": True}, format="json")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data, {"queued": True})
        task.assert_called_once_with(accept_removals=True)

    def test_scan_defaults_to_not_accepting_removals(self):
        self.client.force_authenticate(self.admin)
        with mock.patch("apps.roms.library_views.scan_library_task") as task:
            self.assertEqual(self.client.post(self.scan_url, {}, format="json").status_code, 202)
        task.assert_called_once_with(accept_removals=False)

    def test_scan_conflicts_while_running(self):
        self.client.force_authenticate(self.admin)
        with mock.patch("apps.roms.library_views.scan_running", return_value=True), mock.patch(
            "apps.roms.library_views.scan_library_task"
        ) as task:
            response = self.client.post(self.scan_url, {}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data, {"detail": "A library scan is already running."})
        task.assert_not_called()


class EmptyLibraryRootGuardTests(SimpleTestCase):
    def test_refuses_a_non_temp_or_unprefixed_root(self):
        for root in ("/", str(Path.home()), tempfile.mkdtemp(prefix="not-the-test-library-")):
            with self.subTest(root=root), self.assertRaises(RuntimeError):
                empty_library_root(root)
