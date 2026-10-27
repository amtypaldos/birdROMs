from html import escape
from io import StringIO
from pathlib import Path
from unittest import mock
from urllib.parse import quote

import requests

from django.conf import settings
from django.core.cache import cache
from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, StorageHandler, default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from storages.backends.s3 import S3Storage

from birdroms.storage import FILESYSTEM_STORAGE, S3_STORAGE, build_storages
from birdroms.tasks import scrape_rom_cover
from birdroms.uploads import parse_max_upload_bytes

from .cover_art import (
    best_libretro_name,
    find_libretro,
    find_screenscraper,
    libretro_name_index,
    normalize_title,
    parse_cover_art_settings,
)
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
    def test_tests_use_postgres_and_temp_media_root(self):
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql")
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
        self.assertEqual([rom["title"] for rom in response.data["results"]], ["Existing"])

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


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
LIBRETRO_ONLY = parse_cover_art_settings({"COVER_ART_PROVIDERS": "libretro", "COVER_ART_TIMEOUT": "3"})
BOTH_PROVIDERS = parse_cover_art_settings(
    {
        "COVER_ART_PROVIDERS": "screenscraper,libretro",
        "SS_DEV_ID": "dev",
        "SS_DEV_PASSWORD": "devpass",
        "SS_USER": "me",
        "SS_PASSWORD": "secret",
    }
)


class FakeResponse:
    def __init__(self, status_code=200, content=b"", content_type="image/png", json_data=None):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type}
        self._json = json_data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def json(self):
        return self._json


def fake_http(routes):
    """Mock for `requests.get`: the first route whose key is a substring of the URL answers;
    anything else is a 404. Calls are recorded on the mock."""

    def handler(url, **kwargs):
        for fragment, response in routes.items():
            if fragment in url:
                if isinstance(response, Exception):
                    raise response
                return response
        return FakeResponse(status_code=404, content_type="text/html")

    return mock.Mock(side_effect=handler)


class CoverArtSettingsTests(SimpleTestCase):
    def test_defaults(self):
        config = parse_cover_art_settings({})
        self.assertEqual(config.providers, ("libretro", "screenscraper"))
        self.assertEqual(config.timeout, 10.0)

    def test_order_and_timeout_are_configurable(self):
        config = parse_cover_art_settings({"COVER_ART_PROVIDERS": " ScreenScraper , libretro", "COVER_ART_TIMEOUT": "2.5"})
        self.assertEqual(config.providers, ("screenscraper", "libretro"))
        self.assertEqual(config.timeout, 2.5)

    def test_empty_disables_scraping(self):
        self.assertEqual(parse_cover_art_settings({"COVER_ART_PROVIDERS": ""}).providers, ())

    def test_rejects_unknown_provider_and_bad_timeout(self):
        with self.assertRaises(ImproperlyConfigured):
            parse_cover_art_settings({"COVER_ART_PROVIDERS": "igdb"})
        for bad in ("soon", "0", "-1"):
            with self.assertRaises(ImproperlyConfigured):
                parse_cover_art_settings({"COVER_ART_TIMEOUT": bad})


NES_INDEX_URL = "https://thumbnails.libretro.com/Nintendo%20-%20Nintendo%20Entertainment%20System/Named_Boxarts/"
NES_NAMES = [
    "Super Mario Bros. (World)",
    "Super Mario Bros. 3 (USA) (Rev 1)",
    "Super Mario Bros. 3 (Europe)",
    "Metroid (USA)",
    "Legend of Zelda, The (USA)",
    "Mario & Luigi_ Superstar Saga",
]


def index_listing(names):
    """An Apache-style directory listing like thumbnails.libretro.com serves."""
    rows = "".join(f'<tr><td><a href="{quote(name)}.png">{escape(name)}.png</a></td></tr>' for name in names)
    return FakeResponse(content=f"<html><body><table>{rows}</table></body></html>".encode(), content_type="text/html")


class NormalizeTitleTests(SimpleTestCase):
    def test_normalize_title_strips_tags(self):
        self.assertEqual(normalize_title("Super Mario Bros. (USA) (Rev 1)"), "super mario bros")
        self.assertEqual(normalize_title("Metroid [!] (Europe) [b1]"), "metroid")

    def test_normalize_title_drops_punctuation_and_collapses_whitespace(self):
        self.assertEqual(normalize_title("  Mario & Luigi:   Superstar-Saga! "), "mario luigi superstar saga")
        self.assertEqual(normalize_title("Mario & Luigi_ Superstar Saga"), "mario luigi superstar saga")
        # No-Intro files articles at the end: "Legend of Zelda, The".
        self.assertEqual(normalize_title("Legend of Zelda, The (USA)"), "the legend of zelda")


class BestLibretroNameTests(SimpleTestCase):
    def test_best_match_picks_closest(self):
        self.assertEqual(best_libretro_name("super mario bros 3", "NES", NES_NAMES), "Super Mario Bros. 3 (USA) (Rev 1)")
        self.assertEqual(best_libretro_name("Mario and Luigi Superstar Saga", "GBA", NES_NAMES), "Mario & Luigi_ Superstar Saga")
        self.assertEqual(best_libretro_name("The Legend of Zelda", "NES", NES_NAMES), "Legend of Zelda, The (USA)")

    def test_best_match_rejects_false_positive(self):
        self.assertIsNone(best_libretro_name("Sonic the Hedgehog", "NES", NES_NAMES))
        self.assertIsNone(best_libretro_name("Obscure Homebrew", "NES", NES_NAMES))
        self.assertIsNone(best_libretro_name("Metroid", "NES", []))

    def test_sequels_are_not_confused_with_the_original(self):
        index = ["Sonic the Hedgehog (USA)", "Sonic the Hedgehog 2 (USA)", "Final Fantasy IV (USA)"]
        self.assertEqual(best_libretro_name("Sonic the Hedgehog 2", "x", index), "Sonic the Hedgehog 2 (USA)")
        self.assertEqual(best_libretro_name("Sonic the Hedgehog", "x", index), "Sonic the Hedgehog (USA)")
        self.assertIsNone(best_libretro_name("Sonic the Hedgehog 3", "x", index))
        self.assertIsNone(best_libretro_name("Final Fantasy VI", "x", index))

    def test_prefers_exact_then_usa_among_equal_matches(self):
        index = ["Metroid (Europe)", "Metroid (Japan)", "Metroid (USA)"]
        self.assertEqual(best_libretro_name("Metroid", "NES", index), "Metroid (USA)")
        self.assertEqual(best_libretro_name("Metroid (Japan)", "NES", index), "Metroid (Japan)")


class LibretroNameIndexTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_parses_listing_and_caches_it(self):
        get = fake_http({NES_INDEX_URL: index_listing(NES_NAMES)})
        with mock.patch("apps.roms.cover_art.requests.get", get):
            first = libretro_name_index("Nintendo - Nintendo Entertainment System")
            second = libretro_name_index("Nintendo - Nintendo Entertainment System")

        self.assertEqual(first, NES_NAMES)
        self.assertEqual(second, NES_NAMES)
        get.assert_called_once()

    def test_missing_listing_is_empty_and_not_cached(self):
        with mock.patch("apps.roms.cover_art.requests.get", fake_http({})) as get:
            self.assertEqual(libretro_name_index("Nintendo - Nintendo Entertainment System"), [])
            self.assertEqual(libretro_name_index("Nintendo - Nintendo Entertainment System"), [])
        self.assertEqual(get.call_count, 2)


class ProviderTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_libretro_uses_matched_index_name(self):
        get = fake_http({NES_INDEX_URL: index_listing(NES_NAMES)})
        with mock.patch("apps.roms.cover_art.requests.get", get):
            urls = find_libretro("super mario bros 3", "NES", "roms/smb3.nes", LIBRETRO_ONLY)
        base = "https://thumbnails.libretro.com/Nintendo%20-%20Nintendo%20Entertainment%20System/"
        self.assertEqual(urls[0], f"{base}Named_Boxarts/Super%20Mario%20Bros.%203%20%28USA%29%20%28Rev%201%29.png")
        # The unmatched file-stem candidate ("smb3") is still tried as a plain guess after it.
        self.assertEqual(urls[1], f"{base}Named_Boxarts/smb3.png")
        self.assertEqual(urls[2], f"{base}Named_Titles/Super%20Mario%20Bros.%203%20%28USA%29%20%28Rev%201%29.png")
        self.assertTrue(urls[-1].startswith(f"{base}Named_Snaps/"))

    def test_libretro_guesses_exact_name_when_nothing_matches(self):
        get = fake_http({NES_INDEX_URL: index_listing(NES_NAMES)})
        with mock.patch("apps.roms.cover_art.requests.get", get):
            urls = find_libretro("Obscure Homebrew", "NES", "", LIBRETRO_ONLY)
        self.assertEqual(len(urls), 3)
        self.assertTrue(urls[0].endswith("/Named_Boxarts/Obscure%20Homebrew.png"))

    def test_libretro_urls_map_platform_and_sanitize_title(self):
        with mock.patch("apps.roms.cover_art.requests.get", fake_http({})):
            urls = find_libretro("Mario & Luigi: Superstar Saga", "Game Boy Advance", "roms/mlss.gba", LIBRETRO_ONLY)
        self.assertEqual(
            urls[0],
            "https://thumbnails.libretro.com/Nintendo%20-%20Game%20Boy%20Advance/Named_Boxarts/"
            "Mario%20_%20Luigi_%20Superstar%20Saga.png",
        )
        # Boxart for every name candidate first, then title screens, then snaps.
        self.assertIn("/Named_Boxarts/mlss.png", urls[1])
        self.assertIn("/Named_Titles/", urls[2])
        self.assertIn("/Named_Snaps/", urls[-1])

    def test_libretro_skips_unmapped_platforms(self):
        self.assertEqual(find_libretro("Game", "Disc Image", "game.iso", LIBRETRO_ONLY), [])

    def test_screenscraper_skipped_without_credentials(self):
        with mock.patch("apps.roms.cover_art.requests.get") as get:
            self.assertEqual(find_screenscraper("Metroid", "NES", "metroid.nes", LIBRETRO_ONLY), [])
        get.assert_not_called()

    def test_screenscraper_queries_with_credentials_and_ranks_media(self):
        payload = {
            "response": {
                "jeu": {
                    "medias": [
                        {"type": "ss", "region": "us", "url": "https://ss.example/ss"},
                        {"type": "box-2D", "region": "jp", "url": "https://ss.example/box-jp"},
                        {"type": "box-2D", "region": "us", "url": "https://ss.example/box-us"},
                        {"type": "wheel", "region": "us", "url": "https://ss.example/wheel"},
                    ]
                }
            }
        }
        get = fake_http({"screenscraper.fr": FakeResponse(json_data=payload, content_type="application/json")})
        with mock.patch("apps.roms.cover_art.requests.get", get):
            urls = find_screenscraper("Metroid", "NES", "roms/Metroid (USA).nes", BOTH_PROVIDERS)

        self.assertEqual(urls, ["https://ss.example/box-us", "https://ss.example/box-jp", "https://ss.example/ss"])
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["romnom"], "Metroid (USA).nes")
        self.assertEqual(params["systemeid"], 3)
        self.assertEqual((params["devid"], params["ssid"]), ("dev", "me"))
        self.assertEqual(get.call_args.kwargs["timeout"], 10.0)


@override_settings(COVER_ART=LIBRETRO_ONLY)
class CoverArtScrapeTests(APITestCase):
    list_url = reverse("rom-list")
    boxart = "Nintendo%20-%20Nintendo%20Entertainment%20System/Named_Boxarts/Metroid.png"

    def setUp(self):
        self.admin_user = make_user("admin", "super_admin")
        self.client.force_authenticate(self.admin_user)

    def upload(self, title="Metroid", name="metroid.nes"):
        return self.client.post(self.list_url, {"title": title, "file": dummy_rom(name)}, format="multipart")

    def test_upload_match_stores_cover_in_storage(self):
        get = fake_http({self.boxart: FakeResponse(content=PNG_BYTES)})
        with mock.patch("apps.roms.cover_art.requests.get", get):
            response = self.upload()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rom = ROM.objects.get()
        self.assertEqual(rom.cover_art_source, "libretro")
        self.assertTrue(rom.cover_art.name.startswith("covers/") and rom.cover_art.name.endswith(".png"))
        self.assertTrue(default_storage.exists(rom.cover_art.name))
        # The scrape runs as a background task, so the upload response is serialized before it.
        detail = self.client.get(reverse("rom-detail", args=[rom.pk]))
        self.assertEqual(detail.data["cover_art_url"], f"http://testserver{reverse('rom-cover', args=[rom.pk])}")
        self.assertEqual(detail.data["cover_art_source"], "libretro")
        self.assertEqual(get.call_args.kwargs["timeout"], 3.0)

        cover = self.client.get(reverse("rom-cover", args=[rom.pk]))
        self.assertEqual(cover.status_code, status.HTTP_200_OK)
        self.assertEqual(cover["Content-Type"], "image/png")
        self.assertEqual(b"".join(cover.streaming_content), PNG_BYTES)

    def test_upload_fuzzy_matches_loose_title_via_index(self):
        cache.clear()
        self.addCleanup(cache.clear)
        # Routes match in order, and the image URL contains the index URL, so list the image first.
        get = fake_http(
            {
                f"{NES_INDEX_URL}Metroid%20%28USA%29.png": FakeResponse(content=PNG_BYTES),
                NES_INDEX_URL: index_listing(["Metroid (USA)", "Super Metroid (USA)"]),
            }
        )
        with mock.patch("apps.roms.cover_art.requests.get", get):
            self.upload(title="metroid", name="metroid_fan_rip.nes")

        rom = ROM.objects.get()
        self.assertEqual(rom.cover_art_source, "libretro")
        self.assertTrue(rom.cover_art)

    def test_upload_falls_back_to_title_screen(self):
        titles = self.boxart.replace("Named_Boxarts", "Named_Titles")
        get = fake_http({titles: FakeResponse(content=PNG_BYTES)})
        with mock.patch("apps.roms.cover_art.requests.get", get):
            self.upload()
        self.assertTrue(ROM.objects.get().cover_art)

    def test_upload_without_match_leaves_cover_empty(self):
        with mock.patch("apps.roms.cover_art.requests.get", fake_http({})):
            response = self.upload()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rom = ROM.objects.get()
        self.assertFalse(rom.cover_art)
        self.assertEqual(rom.cover_art_source, "")
        self.assertIsNone(response.data["cover_art_url"])
        self.assertEqual(self.client.get(reverse("rom-cover", args=[rom.pk])).status_code, status.HTTP_404_NOT_FOUND)

    def test_non_image_responses_are_ignored(self):
        get = fake_http({self.boxart: FakeResponse(content=b"<html>", content_type="text/html")})
        with mock.patch("apps.roms.cover_art.requests.get", get):
            self.upload()
        self.assertFalse(ROM.objects.get().cover_art)

    def test_provider_error_does_not_break_upload(self):
        get = fake_http({"thumbnails.libretro.com": requests.ConnectionError("provider down")})
        with mock.patch("apps.roms.cover_art.requests.get", get), self.assertLogs("apps.roms.cover_art", "WARNING"):
            response = self.upload()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(ROM.objects.get().cover_art)

    def test_unexpected_error_does_not_break_upload(self):
        with mock.patch("apps.roms.cover_art.scrape_cover_art", side_effect=RuntimeError("boom")), self.assertLogs(
            "apps.roms.cover_art", "ERROR"
        ):
            response = self.upload()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ROM.objects.count(), 1)

    @override_settings(COVER_ART=BOTH_PROVIDERS)
    def test_failing_provider_falls_through_to_next(self):
        get = fake_http(
            {
                "screenscraper.fr": FakeResponse(status_code=500, content_type="text/plain"),
                self.boxart: FakeResponse(content=PNG_BYTES),
            }
        )
        with mock.patch("apps.roms.cover_art.requests.get", get), self.assertLogs("apps.roms.cover_art", "WARNING"):
            self.upload()
        self.assertEqual(ROM.objects.get().cover_art_source, "libretro")

    @override_settings(COVER_ART=BOTH_PROVIDERS)
    def test_screenscraper_match_is_used_first(self):
        payload = {"response": {"jeu": {"medias": [{"type": "box-2D", "region": "us", "url": "https://ss.example/box"}]}}}
        get = fake_http(
            {
                "screenscraper.fr": FakeResponse(json_data=payload, content_type="application/json"),
                "ss.example/box": FakeResponse(content=b"\xff\xd8jpeg", content_type="image/jpeg"),
            }
        )
        with mock.patch("apps.roms.cover_art.requests.get", get):
            self.upload()
        rom = ROM.objects.get()
        self.assertEqual(rom.cover_art_source, "screenscraper")
        self.assertTrue(rom.cover_art.name.endswith(".jpg"))

    def test_manual_scrape_replaces_existing_art(self):
        with mock.patch("apps.roms.cover_art.requests.get", fake_http({self.boxart: FakeResponse(content=PNG_BYTES)})):
            self.upload()
        rom = ROM.objects.get()
        first = rom.cover_art.name
        new_bytes = PNG_BYTES + b"v2"
        with mock.patch("apps.roms.cover_art.requests.get", fake_http({self.boxart: FakeResponse(content=new_bytes)})):
            response = self.client.post(reverse("rom-scrape-cover", args=[rom.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rom.refresh_from_db()
        with rom.cover_art.open("rb") as handle:
            self.assertEqual(handle.read(), new_bytes)
        if first != rom.cover_art.name:
            self.assertFalse(default_storage.exists(first))

    def test_scrape_cover_returns_404_when_no_image_found(self):
        rom = ROM.objects.create(title="Metroid", file=dummy_rom("metroid.nes"), uploaded_by=self.admin_user)
        with mock.patch("apps.roms.cover_art.requests.get", fake_http({})):
            response = self.client.post(reverse("rom-scrape-cover", args=[rom.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        rom.refresh_from_db()
        self.assertFalse(rom.cover_art)

    def test_cover_requires_role(self):
        with mock.patch("apps.roms.cover_art.requests.get", fake_http({self.boxart: FakeResponse(content=PNG_BYTES)})):
            self.upload()
        url = reverse("rom-cover", args=[ROM.objects.get().pk])

        self.client.force_authenticate(make_user("nobody"))
        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(make_user("reader", "readonly"))
        self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(url).status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class ScrapeCoverTaskTests(APITestCase):
    list_url = reverse("rom-list")

    def setUp(self):
        self.admin_user = make_user("admin", "super_admin")

    def make_rom(self):
        return ROM.objects.create(title="Metroid", file=dummy_rom("metroid.nes"), uploaded_by=self.admin_user)

    def test_upload_enqueues_scrape(self):
        self.client.force_authenticate(self.admin_user)
        with mock.patch("apps.roms.views.scrape_rom_cover") as scrape:
            response = self.client.post(self.list_url, {"title": "Metroid", "file": dummy_rom()}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        scrape.assert_called_once_with(ROM.objects.get().pk)

    def test_scrape_task_missing_rom_is_noop(self):
        with mock.patch("birdroms.tasks.safe_fetch_cover_for_rom") as fetch:
            self.assertFalse(scrape_rom_cover.call_local(999_999))
        fetch.assert_not_called()

    def test_scrape_task_returns_whether_art_changed(self):
        rom = self.make_rom()
        with mock.patch("birdroms.tasks.safe_fetch_cover_for_rom", return_value=True) as fetch:
            self.assertTrue(scrape_rom_cover.call_local(rom.pk))
        fetch.assert_called_once_with(rom)

    def test_scrape_task_swallows_provider_error(self):
        rom = self.make_rom()
        with mock.patch("apps.roms.cover_art.fetch_cover_for_rom", side_effect=RuntimeError("boom")), self.assertLogs(
            "apps.roms.cover_art", "ERROR"
        ):
            self.assertFalse(scrape_rom_cover.call_local(rom.pk))


@override_settings(COVER_ART=LIBRETRO_ONLY)
class BackfillCoverArtCommandTests(TestCase):
    def test_backfills_only_missing_art(self):
        admin_user = make_user("admin", "super_admin")
        metroid = ROM.objects.create(title="Metroid", file=dummy_rom("metroid.nes"), uploaded_by=admin_user)
        unknown = ROM.objects.create(title="Obscure Homebrew", file=dummy_rom("homebrew.nes"), uploaded_by=admin_user)
        existing = ROM.objects.create(title="Metroid", file=dummy_rom("metroid2.nes"), uploaded_by=admin_user)
        existing.cover_art.save("existing.png", ContentFile(b"old"), save=True)
        get = fake_http({CoverArtScrapeTests.boxart: FakeResponse(content=PNG_BYTES)})
        out = StringIO()

        with mock.patch("apps.roms.cover_art.requests.get", get):
            call_command("backfill_cover_art", stdout=out)

        metroid.refresh_from_db()
        unknown.refresh_from_db()
        existing.refresh_from_db()
        self.assertEqual(metroid.cover_art_source, "libretro")
        self.assertFalse(unknown.cover_art)
        with existing.cover_art.open("rb") as handle:
            self.assertEqual(handle.read(), b"old")
        self.assertIn("Cover art saved for 1 ROM(s); 1 without a match.", out.getvalue())


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
        data = self.client.get(reverse("rom-list")).data["results"][0]
        self.assertNotIn("file", data)
        self.assertNotIn(settings.MEDIA_URL, str(data))
        self.assertTrue(data["download_url"].endswith(self.url), data["download_url"])

    def test_media_route_does_not_serve_roms(self):
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(settings.MEDIA_URL + self.rom.file.name)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class UploadValidationTests(APITestCase):
    list_url = reverse("rom-list")

    def setUp(self):
        self.client.force_authenticate(make_user("admin", "super_admin"))

    def upload(self, file, **extra):
        return self.client.post(self.list_url, {"title": "Upload", "file": file, **extra}, format="multipart")

    def test_valid_rom_is_accepted_and_classified(self):
        response = self.upload(dummy_rom("Zelda.nes"))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["platform"], "NES")
        self.assertEqual(response.data["extension"], ".nes")

    def test_archives_are_accepted(self):
        for name in ("pack.zip", "pack.7z"):
            with self.subTest(name=name):
                self.assertEqual(self.upload(dummy_rom(name)).status_code, status.HTTP_201_CREATED)

    def test_unknown_extension_rejected(self):
        response = self.upload(dummy_rom("setup.exe"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", response.data)
        self.assertIn(".exe", str(response.data["file"]))
        self.assertEqual(ROM.objects.count(), 0)

    def test_missing_extension_rejected(self):
        response = self.upload(dummy_rom("README"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", response.data)

    def test_extension_check_is_case_insensitive(self):
        response = self.upload(dummy_rom("Metroid.GBA"))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["extension"], ".gba")

    def test_empty_file_rejected(self):
        response = self.upload(SimpleUploadedFile("empty.nes", b""))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", response.data)
        self.assertEqual(ROM.objects.count(), 0)

    @override_settings(MAX_ROM_UPLOAD_BYTES=8)
    def test_oversized_file_rejected(self):
        response = self.upload(dummy_rom("big.nes"))  # 16 bytes
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file", response.data)
        self.assertEqual(ROM.objects.count(), 0)

    @override_settings(MAX_ROM_UPLOAD_BYTES=16)
    def test_file_at_limit_accepted(self):
        self.assertEqual(self.upload(dummy_rom("exact.nes")).status_code, status.HTTP_201_CREATED)

    def test_platform_can_be_patched_without_reuploading(self):
        rom_id = self.upload(dummy_rom("Shenmue.chd")).data["id"]
        response = self.client.patch(reverse("rom-detail", args=[rom_id]), {"platform": "Sega Dreamcast"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["platform"], "Sega Dreamcast")


class UploadSizeSettingTests(SimpleTestCase):
    def test_default_is_two_gib(self):
        self.assertEqual(parse_max_upload_bytes({}), 2 * 1024**3)

    def test_env_override(self):
        self.assertEqual(parse_max_upload_bytes({"MAX_ROM_UPLOAD_BYTES": "1048576"}), 1048576)

    def test_invalid_values_rejected(self):
        for value in ("abc", "0", "-5"):
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                parse_max_upload_bytes({"MAX_ROM_UPLOAD_BYTES": value})


class ROMListQueryTests(APITestCase):
    list_url = reverse("rom-list")
    platforms_url = reverse("rom-platforms")

    def setUp(self):
        self.admin_user = make_user("admin", "super_admin")
        self.client.force_authenticate(make_user("reader", "readonly"))

    def add(self, title, filename):
        return ROM.objects.create(title=title, file=dummy_rom(filename), uploaded_by=self.admin_user)

    def titles(self, response):
        return sorted(rom["title"] for rom in response.data["results"])

    def test_list_returns_paginated_envelope(self):
        self.add("Zelda", "zelda.nes")

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data), {"count", "next", "previous", "results"})
        self.assertEqual(response.data["count"], 1)
        self.assertIsNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

    def test_default_page_size_is_24_and_pages_link(self):
        for i in range(30):
            self.add(f"Game {i:02d}", f"game{i}.nes")

        first = self.client.get(self.list_url)
        self.assertEqual(first.data["count"], 30)
        self.assertEqual(len(first.data["results"]), 24)
        self.assertIsNotNone(first.data["next"])

        second = self.client.get(self.list_url, {"page": 2})
        self.assertEqual(len(second.data["results"]), 6)
        self.assertIsNone(second.data["next"])
        self.assertIsNotNone(second.data["previous"])
        seen = {rom["id"] for rom in first.data["results"]} | {rom["id"] for rom in second.data["results"]}
        self.assertEqual(len(seen), 30)

    def test_page_size_param_is_capped(self):
        for i in range(3):
            self.add(f"Game {i}", f"game{i}.nes")
        self.assertEqual(len(self.client.get(self.list_url, {"page_size": 2}).data["results"]), 2)
        self.assertEqual(len(self.client.get(self.list_url, {"page_size": 100000}).data["results"]), 3)

    def test_out_of_range_page_returns_404(self):
        self.add("Zelda", "zelda.nes")
        self.assertEqual(self.client.get(self.list_url, {"page": 9}).status_code, status.HTTP_404_NOT_FOUND)

    def test_search_is_case_insensitive_partial_title_match(self):
        self.add("The Legend of Zelda", "zelda.nes")
        self.add("Zelda II", "zelda2.nes")
        self.add("Metroid", "metroid.nes")

        response = self.client.get(self.list_url, {"search": "zELd"})

        self.assertEqual(response.data["count"], 2)
        self.assertEqual(self.titles(response), ["The Legend of Zelda", "Zelda II"])

    def test_platform_filter_is_exact(self):
        self.add("Zelda", "zelda.nes")
        self.add("Minish Cap", "minish.gba")

        response = self.client.get(self.list_url, {"platform": "Game Boy Advance"})
        self.assertEqual(self.titles(response), ["Minish Cap"])

        partial = self.client.get(self.list_url, {"platform": "Game Boy"})
        self.assertEqual(partial.data["count"], 0)

    def test_search_and_platform_combine(self):
        self.add("Zelda", "zelda.nes")
        self.add("Zelda Minish Cap", "minish.gba")
        self.add("Metroid Fusion", "fusion.gba")

        response = self.client.get(self.list_url, {"search": "zelda", "platform": "Game Boy Advance"})

        self.assertEqual(self.titles(response), ["Zelda Minish Cap"])

    def test_blank_filters_are_ignored(self):
        self.add("Zelda", "zelda.nes")
        response = self.client.get(self.list_url, {"search": "  ", "platform": ""})
        self.assertEqual(response.data["count"], 1)

    def test_platforms_endpoint_lists_distinct_sorted_platforms(self):
        self.add("Zelda", "zelda.nes")
        self.add("Metroid", "metroid.nes")
        self.add("Minish Cap", "minish.gba")

        response = self.client.get(self.platforms_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, ["Game Boy Advance", "NES"])

    def test_platforms_endpoint_requires_a_role(self):
        self.client.force_authenticate(make_user("nobody"))
        self.assertEqual(self.client.get(self.platforms_url).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(None)
        self.assertIn(
            self.client.get(self.platforms_url).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
