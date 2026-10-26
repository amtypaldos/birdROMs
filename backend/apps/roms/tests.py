from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.files.storage import FileSystemStorage, StorageHandler, default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from storages.backends.s3 import S3Storage

from birdroms.storage import FILESYSTEM_STORAGE, S3_STORAGE, build_storages

from .models import ROM
from .services import (
    EXTENSION_TO_PLATFORM,
    SUPPORTED_EXTENSIONS,
    SUPPORTED_PLATFORMS,
    UNKNOWN_PLATFORM,
    classify_platform_from_extension,
)


def make_user(username, group_name=None):
    user = User.objects.create_user(username=username, password="test-pass-123")
    if group_name:
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
    return user


def dummy_rom(name="game.nes"):
    return SimpleUploadedFile(name, b"\x4e\x45\x53\x1a" + b"\x00" * 12, content_type="application/octet-stream")


class TestSettingsTests(SimpleTestCase):
    def test_tests_use_sqlite_and_temp_media_root(self):
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3")
        self.assertNotEqual(Path(settings.MEDIA_ROOT).resolve(), (settings.BASE_DIR / "media").resolve())


class ROMPermissionTests(APITestCase):
    list_url = reverse("rom-list")

    def setUp(self):
        self.readonly_user = make_user("reader", "readonly")
        self.admin_user = make_user("admin", "super_admin")

    def test_anonymous_cannot_list(self):
        response = self.client.get(self.list_url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_anonymous_cannot_create(self):
        response = self.client.post(self.list_url, {"title": "Nope", "file": dummy_rom()}, format="multipart")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertEqual(ROM.objects.count(), 0)

    def test_user_without_role_cannot_list(self):
        self.client.force_authenticate(make_user("nobody"))
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_readonly_can_list(self):
        ROM.objects.create(title="Existing", file=dummy_rom("existing.gba"), uploaded_by=self.admin_user)
        self.client.force_authenticate(self.readonly_user)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([rom["title"] for rom in response.data], ["Existing"])

    def test_readonly_cannot_create(self):
        self.client.force_authenticate(self.readonly_user)
        response = self.client.post(self.list_url, {"title": "Nope", "file": dummy_rom()}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ROM.objects.count(), 0)

    def test_super_admin_can_create_with_auto_classification(self):
        self.client.force_authenticate(self.admin_user)

        response = self.client.post(
            self.list_url, {"title": "Super Mario Bros.", "file": dummy_rom("Super Mario Bros.NES")}, format="multipart"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rom = ROM.objects.get(pk=response.data["id"])
        self.assertEqual(rom.extension, ".nes")
        self.assertEqual(rom.platform, "NES")
        self.assertEqual(rom.uploaded_by, self.admin_user)
        self.assertEqual(response.data["extension"], ".nes")
        self.assertEqual(response.data["platform"], "NES")
        self.assertTrue(Path(rom.file.path).resolve().is_relative_to(Path(settings.MEDIA_ROOT).resolve()))


class ScrapeCoverTests(APITestCase):
    def test_scrape_cover_returns_404_when_no_image_found(self):
        admin_user = make_user("admin", "super_admin")
        rom = ROM.objects.create(title="Metroid", file=dummy_rom("metroid.nes"), uploaded_by=admin_user)
        self.client.force_authenticate(admin_user)

        response = self.client.post(reverse("rom-scrape-cover", args=[rom.pk]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        rom.refresh_from_db()
        self.assertEqual(rom.cover_art_url, "")


class PlatformClassificationTests(SimpleTestCase):
    def test_classifies_representative_sample_across_systems(self):
        cases = {
            "Super Mario Bros.nes": "NES",
            "Chrono Trigger.sfc": "SNES",
            "Earthbound.smc": "SNES",
            "Super Mario 64.z64": "Nintendo 64",
            "Zelda OoT.v64": "Nintendo 64",
            "Wind Waker.rvz": "Nintendo GameCube",
            "Melee.gcm": "Nintendo GameCube",
            "Mario Kart Wii.wbfs": "Nintendo Wii",
            "Tetris.gb": "Game Boy",
            "Pokemon Crystal.gbc": "Game Boy Color",
            "Metroid Fusion.gba": "Game Boy Advance",
            "Mario Kart DS.nds": "Nintendo DS",
            "Ocarina 3D.3ds": "Nintendo 3DS",
            "Eshop Title.cia": "Nintendo 3DS",
            "Alex Kidd.sms": "Sega Master System",
            "Sonic.gen": "Sega Genesis",
            "Sonic 2.md": "Sega Genesis",
            "Streets of Rage.smd": "Sega Genesis",
            "Shinobi.gg": "Sega Game Gear",
            "Knuckles Chaotix.32x": "Sega 32X",
            "Shenmue.gdi": "Sega Dreamcast",
            "Jet Set Radio.cdi": "Sega Dreamcast",
            "FF7.pbp": "Sony PlayStation",
            "Patapon.cso": "Sony PSP",
            "Bonk.pce": "PC Engine / TurboGrafx-16",
            "SNK vs Capcom.ngp": "Neo Geo Pocket",
            "Metal Slug.ngc": "Neo Geo Pocket Color",
            "Gunpey.ws": "WonderSwan",
            "Final Fantasy.wsc": "WonderSwan Color",
            "Pitfall.a26": "Atari 2600",
            "Ninja Golf.a78": "Atari 7800",
            "California Games.lnx": "Atari Lynx",
            "Tempest 2000.j64": "Atari Jaguar",
            "Alien vs Predator.jag": "Atari Jaguar",
        }
        for filename, platform in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(classify_platform_from_extension(filename), platform)

    def test_ambiguous_extensions_map_to_generic_labels(self):
        for filename in ("game.iso", "game.bin", "game.cue", "game.chd"):
            with self.subTest(filename=filename):
                self.assertEqual(classify_platform_from_extension(filename), "Disc Image")
        for filename in ("game.zip", "game.7z"):
            with self.subTest(filename=filename):
                self.assertEqual(classify_platform_from_extension(filename), "Archive")

    def test_case_insensitive_and_multi_dot_filenames(self):
        self.assertEqual(classify_platform_from_extension("Super.Mario.World.SFC"), "SNES")
        self.assertEqual(classify_platform_from_extension("roms/v1.0.final.Gba"), "Game Boy Advance")
        # The last suffix wins, not a substring match (".smd" must not be read as ".md").
        self.assertEqual(classify_platform_from_extension("game.md.smd"), "Sega Genesis")
        self.assertEqual(classify_platform_from_extension("game.nes.zip"), "Archive")

    def test_unknown_or_missing_extension(self):
        self.assertEqual(classify_platform_from_extension("readme.txt"), UNKNOWN_PLATFORM)
        self.assertEqual(classify_platform_from_extension("noextension"), UNKNOWN_PLATFORM)
        self.assertEqual(classify_platform_from_extension(".nes"), UNKNOWN_PLATFORM)

    def test_supported_constants_derived_from_map(self):
        self.assertEqual(SUPPORTED_EXTENSIONS, frozenset(EXTENSION_TO_PLATFORM))
        self.assertIn("SNES", SUPPORTED_PLATFORMS)
        self.assertIn("Disc Image", SUPPORTED_PLATFORMS)
        self.assertEqual(list(SUPPORTED_PLATFORMS), sorted(set(EXTENSION_TO_PLATFORM.values())))
        for ext in SUPPORTED_EXTENSIONS:
            self.assertTrue(ext.startswith(".") and ext == ext.lower(), ext)


class PlatformOverrideTests(APITestCase):
    def setUp(self):
        self.admin_user = make_user("admin", "super_admin")
        self.client.force_authenticate(self.admin_user)

    def test_blank_platform_is_auto_classified(self):
        response = self.client.post(
            reverse("rom-list"), {"title": "Shenmue", "file": dummy_rom("Shenmue.chd")}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["platform"], "Disc Image")
        self.assertEqual(response.data["extension"], ".chd")

    def test_explicit_platform_overrides_ambiguous_extension(self):
        response = self.client.post(
            reverse("rom-list"),
            {"title": "Panzer Dragoon", "platform": "Sega Saturn", "file": dummy_rom("Panzer Dragoon.chd")},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ROM.objects.get(pk=response.data["id"]).platform, "Sega Saturn")

    def test_platform_can_be_corrected_after_upload(self):
        rom = ROM.objects.create(title="FF7", file=dummy_rom("ff7.bin"), uploaded_by=self.admin_user)
        self.assertEqual(rom.platform, "Disc Image")

        response = self.client.patch(reverse("rom-detail", args=[rom.pk]), {"platform": "Sony PlayStation"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rom.refresh_from_db()
        self.assertEqual(rom.platform, "Sony PlayStation")


class StorageBackendTests(SimpleTestCase):
    S3_ENV = {
        "STORAGE_BACKEND": "s3",
        "S3_BUCKET_NAME": "roms",
        "S3_ACCESS_KEY_ID": "test-access",
        "S3_SECRET_ACCESS_KEY": "test-secret",
        "S3_ENDPOINT_URL": "http://minio:9000",
        "S3_REGION": "us-east-1",
        "S3_CUSTOM_DOMAIN": "cdn.example.com",
        "S3_PATH_STYLE": "true",
    }

    def test_filesystem_is_default(self):
        storages_setting = build_storages({})
        self.assertEqual(storages_setting["default"]["BACKEND"], FILESYSTEM_STORAGE)
        self.assertEqual(build_storages({"STORAGE_BACKEND": "filesystem"}), storages_setting)

    def test_s3_backend_selected_and_configured_from_env(self):
        storages_setting = build_storages(self.S3_ENV)
        default = storages_setting["default"]
        self.assertEqual(default["BACKEND"], S3_STORAGE)
        self.assertEqual(default["OPTIONS"]["bucket_name"], "roms")
        self.assertEqual(default["OPTIONS"]["endpoint_url"], "http://minio:9000")
        self.assertEqual(default["OPTIONS"]["addressing_style"], "path")
        self.assertIsNone(default["OPTIONS"]["default_acl"])

        # Wiring: Django instantiates S3Storage as default storage (no network needed).
        storage = StorageHandler(storages_setting)["default"]
        self.assertIsInstance(storage, S3Storage)
        self.assertEqual(storage.bucket_name, "roms")
        self.assertEqual(storage.endpoint_url, "http://minio:9000")
        self.assertEqual(storage.region_name, "us-east-1")
        self.assertEqual(storage.custom_domain, "cdn.example.com")
        self.assertEqual(storage.addressing_style, "path")
        self.assertEqual(storage.access_key, "test-access")

    def test_s3_optional_settings_omitted_when_unset(self):
        options = build_storages({"STORAGE_BACKEND": "S3", "S3_BUCKET_NAME": "roms"})["default"]["OPTIONS"]
        for key in ("endpoint_url", "region_name", "custom_domain", "addressing_style"):
            self.assertNotIn(key, options)

    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            build_storages({"STORAGE_BACKEND": "ftp"})


class FilesystemStorageRoundTripTests(APITestCase):
    def test_tests_use_filesystem_storage(self):
        self.assertIsInstance(default_storage, FileSystemStorage)

    def test_uploaded_rom_round_trips(self):
        admin = make_user("admin", "super_admin")
        payload = b"\x4e\x45\x53\x1a" + bytes(range(64))
        rom = ROM.objects.create(
            title="Round Trip",
            file=SimpleUploadedFile("trip.nes", payload),
            uploaded_by=admin,
        )
        self.assertTrue(default_storage.exists(rom.file.name))
        self.assertTrue(Path(rom.file.path).is_relative_to(Path(settings.MEDIA_ROOT)))
        rom = ROM.objects.get(pk=rom.pk)
        with rom.file.open("rb") as fh:
            self.assertEqual(fh.read(), payload)


class ROMDownloadTests(APITestCase):
    PAYLOAD = b"\x4e\x45\x53\x1a" + bytes(range(32))

    def setUp(self):
        self.admin_user = make_user("admin", "super_admin")
        self.rom = ROM.objects.create(
            title="Zelda", file=SimpleUploadedFile("zelda.nes", self.PAYLOAD), uploaded_by=self.admin_user
        )
        self.url = reverse("rom-download", args=[self.rom.pk])

    def assert_downloads_rom(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(response.streaming_content), self.PAYLOAD)
        disposition = response["Content-Disposition"]
        self.assertTrue(disposition.startswith("attachment;"), disposition)
        self.assertIn('filename="Zelda.nes"', disposition)

    def test_super_admin_can_download(self):
        self.client.force_authenticate(self.admin_user)
        self.assert_downloads_rom(self.client.get(self.url))

    def test_readonly_can_download(self):
        self.client.force_authenticate(make_user("reader", "readonly"))
        self.assert_downloads_rom(self.client.get(self.url))

    def test_anonymous_cannot_download(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_user_without_role_cannot_download(self):
        self.client.force_authenticate(make_user("nobody"))
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)

    def test_download_filename_strips_path_separators(self):
        self.rom.title = "../etc/passwd"
        self.rom.save()
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(self.url)
        self.assertIn('filename=".._etc_passwd.nes"', response["Content-Disposition"])

    def test_unknown_id_returns_404(self):
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(reverse("rom-download", args=[self.rom.pk + 999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_serializer_exposes_download_endpoint_not_media_url(self):
        self.client.force_authenticate(make_user("reader", "readonly"))
        data = self.client.get(reverse("rom-list")).data[0]
        self.assertNotIn("file", data)
        self.assertNotIn(settings.MEDIA_URL, str(data))
        self.assertTrue(data["download_url"].endswith(self.url), data["download_url"])

    def test_media_route_does_not_serve_roms(self):
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(settings.MEDIA_URL + self.rom.file.name)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
