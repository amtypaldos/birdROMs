import importlib
from difflib import SequenceMatcher
from html import escape
from io import StringIO
from pathlib import Path
from unittest import mock
from urllib.parse import quote

import requests

from django.apps import apps as django_apps
from django.contrib import admin
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
from birdroms.tasks import scrape_rom_cover, sweep_missing_cover_art
from birdroms.uploads import parse_max_upload_bytes

from .cover_art import (
    LIBRETRO_MATCH_THRESHOLD,
    ScreenScraperGame,
    best_libretro_name,
    download_image,
    is_allowed_image_url,
    redact_secrets,
    scrape_cover_art,
    fetch_cover_for_rom,
    find_libretro,
    find_screenscraper,
    libretro_name_index,
    lookup_screenscraper_game,
    normalize_title,
    parse_cover_art_settings,
    parse_screenscraper_metadata,
    scrape_rom,
)
from .admin import ROMAdmin
from .cover_art import _title_candidates, _without_dedup_suffix
from .models import ROM, Playlist, PlaylistItem
from .services import (
    EXTENSION_TO_PLATFORM,
    SUPPORTED_EXTENSIONS,
    SUPPORTED_PLATFORMS,
    UNKNOWN_PLATFORM,
    classify_platform_from_extension,
    parse_rom_filename,
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

    def test_any_authed_user_can_upload(self):
        # Open uploads are deliberate for now (RBAC deferred): a roleless user can upload.
        nobody = make_user("nobody")
        self.client.force_authenticate(nobody)

        response = self.client.post(self.list_url, {"title": "Mine", "file": dummy_rom()}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ROM.objects.get(pk=response.data["id"]).uploaded_by, nobody)

    def test_readonly_can_now_create(self):
        self.client.force_authenticate(self.readonly_user)

        response = self.client.post(self.list_url, {"title": "Mine", "file": dummy_rom()}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ROM.objects.get(pk=response.data["id"]).uploaded_by, self.readonly_user)

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
BOTH_PROVIDERS_ENV = {
    "COVER_ART_PROVIDERS": "screenscraper,libretro",
    "SS_DEV_ID": "dev",
    "SS_DEV_PASSWORD": "devpass",
    "SS_USER": "me",
    "SS_PASSWORD": "secret",
}
BOTH_PROVIDERS = parse_cover_art_settings(BOTH_PROVIDERS_ENV)


class FakeResponse:
    def __init__(self, status_code=200, content=b"", content_type="image/png", json_data=None, headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type, **(headers or {})}
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


    def test_clean_title_matches_tagged_title(self):
        self.assertEqual(normalize_title("Bomberman 64"), normalize_title("Bomberman 64 (U) [!]"))


class ParseRomFilenameTests(SimpleTestCase):
    CASES = [
        ("Bomberman 64 (U) [!].z64", "Bomberman 64", ("USA", "Verified good dump")),
        ("Donkey Kong 64 (U) [!].z64.z64", "Donkey Kong 64", ("USA", "Verified good dump")),
        ("6111 - Pokemon Black 2 (US) (frieNDS).nds", "Pokemon Black 2", ("USA", "frieNDS")),
        ("1943 - The Battle of Midway (USA).nes", "1943 - The Battle of Midway", ("USA",)),
        (
            "Legend of Zelda, The - The Minish Cap (USA).gba",
            "The Legend of Zelda - The Minish Cap",
            ("USA",),
        ),
        ("Super_Mario_World.sfc", "Super Mario World", ()),
        ("Sonic the Hedgehog 2 (World) (Rev A).md", "Sonic the Hedgehog 2", ("World", "Rev A")),
        ("Pokemon - Emerald Version (USA, Europe).gba", "Pokemon - Emerald Version", ("USA, Europe",)),
        ("Some Game (Europe) (En,Fr,De) (Beta).gba", "Some Game", ("Europe", "En, Fr, De", "Beta")),
        ("Hack Game (U) [h1C] [T+Eng1.0].nes", "Hack Game", ("USA", "Hack", "Translation")),
        ("Proto Thing (Japan) (Proto) (Unl).gb", "Proto Thing", ("Japan", "Prototype", "Unlicensed")),
        ("Duplicate (USA) (USA).gba", "Duplicate", ("USA",)),
        ("(Beta).gba", "(Beta)", ("Beta",)),
        ("Dr. Mario", "Dr. Mario", ()),
        ("Bomberman 64 (U) [!]", "Bomberman 64", ("USA", "Verified good dump")),
    ]

    def test_required_cases(self):
        for name, title, tags in self.CASES:
            with self.subTest(name=name):
                parsed = parse_rom_filename(name)
                self.assertEqual(parsed.title, title)
                self.assertEqual(parsed.tags, tags)

    def test_trailing_article_variants(self):
        self.assertEqual(parse_rom_filename("Game, A.nes").title, "A Game")
        self.assertEqual(parse_rom_filename("Thing, An (USA).nes").title, "An Thing")

    def test_empty_title_falls_back_to_stem_then_name(self):
        self.assertEqual(parse_rom_filename("  .gba").title, ".gba")

    def test_bracket_flags(self):
        parsed = parse_rom_filename("X [a] [b1] [f] [o] [p] [t2] [weird].nes")
        self.assertEqual(
            parsed.tags, ("Alternate", "Bad dump", "Fixed", "Overdump", "Pirate", "Trained", "weird")
        )


class BestLibretroNameTests(SimpleTestCase):
    def test_best_match_picks_closest(self):
        self.assertEqual(best_libretro_name("super mario bros 3", "NES", NES_NAMES), "Super Mario Bros. 3 (USA) (Rev 1)")
        self.assertEqual(best_libretro_name("Mario and Luigi Superstar Saga", "GBA", NES_NAMES), "Mario & Luigi_ Superstar Saga")
        self.assertEqual(best_libretro_name("The Legend of Zelda", "NES", NES_NAMES), "Legend of Zelda, The (USA)")

    def test_best_match_rejects_false_positive(self):
        self.assertIsNone(best_libretro_name("Obscure Homebrew", "NES", NES_NAMES))
        # A true near-miss: the strings are similar enough to pass the threshold on ratio alone
        # (vs "Super Mario Bros."), so only the sequel guard rejects it.
        ratio = SequenceMatcher(None, normalize_title("Super Mario Bros. 2"), normalize_title("Super Mario Bros. (World)")).ratio()
        self.assertGreaterEqual(ratio, LIBRETRO_MATCH_THRESHOLD)
        self.assertIsNone(best_libretro_name("Super Mario Bros. 2", "NES", NES_NAMES))
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

    def test_redirect_is_refused_and_not_followed(self):
        redirect = FakeResponse(status_code=302, content_type="text/html", headers={"Location": "http://169.254.169.254/"})
        get = fake_http({NES_INDEX_URL: redirect})
        with mock.patch("apps.roms.cover_art.requests.get", get):
            self.assertEqual(libretro_name_index("Nintendo - Nintendo Entertainment System"), [])
        get.assert_called_once()
        self.assertIs(get.call_args.kwargs["allow_redirects"], False)

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

    def test_libretro_guesses_exact_name_when_index_fetch_fails(self):
        for failure in (requests.ConnectionError("down"), FakeResponse(status_code=503, content_type="text/html")):
            with self.subTest(failure=failure):
                get = fake_http({NES_INDEX_URL: failure})
                with mock.patch("apps.roms.cover_art.requests.get", get), self.assertLogs("apps.roms.cover_art", "WARNING"):
                    urls = find_libretro("Metroid", "NES", "", LIBRETRO_ONLY)
                self.assertEqual(len(urls), 3)
                self.assertTrue(urls[0].endswith("/Named_Boxarts/Metroid.png"))

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


SS_JEU = {
    "medias": [{"type": "box-2D", "region": "us", "url": "https://media.screenscraper.fr/box"}],
    "synopsis": [
        {"langue": "fr", "text": "Une chasseuse de primes."},
        {"langue": "en", "text": "A bounty hunter explores planet Zebes."},
    ],
    "genres": [
        {"id": "1", "noms": [{"langue": "fr", "text": "Plateforme"}, {"langue": "en", "text": "Platform"}]},
        {"id": "2", "noms": [{"langue": "en", "text": "Action"}]},
    ],
    "dates": [{"region": "jp", "text": "1986-08-06"}, {"region": "us", "text": "1987-08-15"}],
    "developpeur": {"id": "1", "text": "Nintendo R&D1"},
    "editeur": {"id": "2", "text": "Nintendo"},
    "joueurs": {"text": "1"},
    "note": {"text": "17"},
}
SS_METADATA = {
    "description": "A bounty hunter explores planet Zebes.",
    "genre": "Platform, Action",
    "release_year": 1987,
    "developer": "Nintendo R&D1",
    "publisher": "Nintendo",
    "players": "1",
    "rating": "17/20",
    "region": "us",
}


class ParseScreenScraperMetadataTests(SimpleTestCase):
    def test_parse_ss_metadata(self):
        self.assertEqual(parse_screenscraper_metadata(SS_JEU), SS_METADATA)

    def test_description_prefers_english_then_any_language(self):
        jeu = {"synopsis": [{"langue": "de", "text": "Deutsch"}, {"langue": "fr", "text": "Francais"}]}
        self.assertEqual(parse_screenscraper_metadata(jeu), {"description": "Deutsch"})

    def test_release_date_prefers_region_order_and_tolerates_year_only(self):
        jeu = {"dates": [{"region": "eu", "text": "1988"}, {"region": "jp", "text": "1986-08-06"}]}
        self.assertEqual(parse_screenscraper_metadata(jeu), {"release_year": 1988, "region": "eu"})

    def test_missing_and_malformed_fields_are_omitted(self):
        self.assertEqual(parse_screenscraper_metadata({}), {})
        jeu = {"dates": [{"region": "us", "text": "unknown"}], "synopsis": "bad", "note": {"text": ""}, "joueurs": None}
        self.assertEqual(parse_screenscraper_metadata(jeu), {})

    def test_values_are_clipped_to_column_width(self):
        jeu = {"developpeur": {"text": "x" * 1000}}
        self.assertEqual(len(parse_screenscraper_metadata(jeu)["developer"]), ROM._meta.get_field("developer").max_length)


@override_settings(COVER_ART=BOTH_PROVIDERS)
class ScreenScraperMetadataTests(APITestCase):
    def setUp(self):
        self.admin_user = make_user("admin", "super_admin")
        self.rom = ROM.objects.create(title="Metroid", file=dummy_rom("metroid.nes"), uploaded_by=self.admin_user)

    def ss_http(self, jeu=SS_JEU):
        return fake_http(
            {
                "media.screenscraper.fr/box": FakeResponse(content=b"\xff\xd8jpeg", content_type="image/jpeg"),
                "screenscraper.fr": FakeResponse(json_data={"response": {"jeu": jeu}}, content_type="application/json"),
            }
        )

    def test_fetch_sets_metadata(self):
        with mock.patch("apps.roms.cover_art.requests.get", self.ss_http()):
            self.assertTrue(fetch_cover_for_rom(self.rom))

        self.rom.refresh_from_db()
        for field, value in SS_METADATA.items():
            self.assertEqual(getattr(self.rom, field), value, field)
        self.assertEqual(self.rom.cover_art_source, "screenscraper")
        self.assertTrue(self.rom.cover_art)

    def test_metadata_is_fetched_even_when_libretro_supplies_the_cover(self):
        config = parse_cover_art_settings({**BOTH_PROVIDERS_ENV, "COVER_ART_PROVIDERS": "libretro,screenscraper"})
        boxart = CoverArtScrapeTests.boxart
        get = fake_http(
            {
                "screenscraper.fr": FakeResponse(json_data={"response": {"jeu": SS_JEU}}, content_type="application/json"),
                boxart: FakeResponse(content=PNG_BYTES),
            }
        )
        with mock.patch("apps.roms.cover_art.requests.get", get):
            self.assertTrue(fetch_cover_for_rom(self.rom, config))

        self.rom.refresh_from_db()
        self.assertEqual(self.rom.cover_art_source, "libretro")
        self.assertEqual(self.rom.genre, "Platform, Action")
        self.assertEqual(self.rom.release_year, 1987)
        ss_calls = [c for c in get.call_args_list if "screenscraper.fr" in c.args[0]]
        self.assertEqual(len(ss_calls), 1)

    def test_lookup_refuses_redirects(self):
        redirect = FakeResponse(status_code=302, content_type="text/html", headers={"Location": "http://localhost/internal"})
        get = fake_http({"screenscraper.fr": redirect})
        with mock.patch("apps.roms.cover_art.requests.get", get):
            with self.assertRaises(ValueError):
                lookup_screenscraper_game("Metroid", "NES", "metroid.nes", BOTH_PROVIDERS)
        get.assert_called_once()
        self.assertIs(get.call_args.kwargs["allow_redirects"], False)

    def test_redirecting_lookup_degrades_gracefully(self):
        redirect = FakeResponse(status_code=302, content_type="text/html")
        with mock.patch("apps.roms.cover_art.requests.get", fake_http({"screenscraper.fr": redirect})), self.assertLogs(
            "apps.roms.cover_art", "WARNING"
        ):
            self.assertFalse(fetch_cover_for_rom(self.rom))
        self.rom.refresh_from_db()
        self.assertFalse(self.rom.cover_art)

    def test_metadata_saved_even_without_cover_image(self):
        jeu = {key: value for key, value in SS_JEU.items() if key != "medias"}
        with mock.patch("apps.roms.cover_art.requests.get", self.ss_http(jeu)):
            self.assertFalse(fetch_cover_for_rom(self.rom))  # Returns whether new art was saved.

        self.rom.refresh_from_db()
        self.assertFalse(self.rom.cover_art)
        self.assertEqual(self.rom.publisher, "Nintendo")

    def test_without_credentials_nothing_changes(self):
        boxart = CoverArtScrapeTests.boxart
        get = fake_http({boxart: FakeResponse(content=PNG_BYTES)})
        with mock.patch("apps.roms.cover_art.requests.get", get):
            self.assertTrue(fetch_cover_for_rom(self.rom, LIBRETRO_ONLY))
            self.assertFalse(any("screenscraper.fr" in c.args[0] for c in get.call_args_list))

        self.rom.refresh_from_db()
        self.assertEqual(self.rom.cover_art_source, "libretro")
        self.assertEqual((self.rom.description, self.rom.genre, self.rom.region), ("", "", ""))
        self.assertIsNone(self.rom.release_year)

    def test_screenscraper_failure_degrades_to_libretro_cover_without_metadata(self):
        get = fake_http(
            {
                "screenscraper.fr": FakeResponse(status_code=500, content_type="text/plain"),
                CoverArtScrapeTests.boxart: FakeResponse(content=PNG_BYTES),
            }
        )
        with mock.patch("apps.roms.cover_art.requests.get", get), self.assertLogs("apps.roms.cover_art", "WARNING"):
            self.assertTrue(fetch_cover_for_rom(self.rom))

        self.rom.refresh_from_db()
        self.assertEqual(self.rom.cover_art_source, "libretro")
        self.assertEqual(self.rom.description, "")
        ss_calls = [c for c in get.call_args_list if "screenscraper.fr" in c.args[0]]
        self.assertEqual(len(ss_calls), 1)  # The failed lookup is not retried for metadata.

    def test_concurrent_scrape_no_corruption(self):
        with mock.patch("apps.roms.cover_art.requests.get", self.ss_http()):
            fetch_cover_for_rom(self.rom)
            fetch_cover_for_rom(self.rom)

        self.rom.refresh_from_db()
        _, stored = default_storage.listdir("covers")
        covers = [name for name in stored if name.startswith(f"rom-{self.rom.pk}")]
        self.assertEqual(covers, [Path(self.rom.cover_art.name).name])
        with self.rom.cover_art.open("rb") as handle:
            self.assertEqual(handle.read(), b"\xff\xd8jpeg")
        for field, value in SS_METADATA.items():
            self.assertEqual(getattr(self.rom, field), value, field)

    def test_serializer_exposes_metadata_read_only(self):
        self.client.force_authenticate(self.admin_user)
        detail = reverse("rom-detail", args=[self.rom.pk])
        with mock.patch("apps.roms.cover_art.requests.get", self.ss_http()):
            fetch_cover_for_rom(self.rom)

        data = self.client.get(detail).data
        for field, value in SS_METADATA.items():
            self.assertEqual(data[field], value, field)
        self.assertEqual(self.client.patch(detail, {"genre": "Hacked", "release_year": 1}).status_code, status.HTTP_200_OK)
        self.rom.refresh_from_db()
        self.assertEqual((self.rom.genre, self.rom.release_year), ("Platform, Action", 1987))


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
        payload = {
            "response": {"jeu": {"medias": [{"type": "box-2D", "region": "us", "url": "https://media.screenscraper.fr/box"}]}}
        }
        get = fake_http(
            {
                "media.screenscraper.fr/box": FakeResponse(content=b"\xff\xd8jpeg", content_type="image/jpeg"),
                "screenscraper.fr": FakeResponse(json_data=payload, content_type="application/json"),
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

    def test_scrape_cover_returns_200_when_only_metadata_is_found(self):
        rom = ROM.objects.create(title="Metroid", file=dummy_rom("metroid.nes"), uploaded_by=self.admin_user)
        jeu = {key: value for key, value in SS_JEU.items() if key != "medias"}
        get = fake_http(
            {"screenscraper.fr": FakeResponse(json_data={"response": {"jeu": jeu}}, content_type="application/json")}
        )
        with mock.patch("apps.roms.cover_art.requests.get", get), override_settings(COVER_ART=BOTH_PROVIDERS):
            response = self.client.post(reverse("rom-scrape-cover", args=[rom.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rom.refresh_from_db()
        self.assertFalse(rom.cover_art)
        self.assertEqual(rom.publisher, "Nintendo")

    def test_scrape_cover_never_500s_on_unexpected_error(self):
        rom = ROM.objects.create(title="Metroid", file=dummy_rom("metroid.nes"), uploaded_by=self.admin_user)
        with mock.patch("apps.roms.views.scrape_rom", side_effect=RuntimeError("boom")), self.assertLogs(
            "apps.roms.views", "ERROR"
        ):
            response = self.client.post(reverse("rom-scrape-cover", args=[rom.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

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


class ScrapeRomFilenameTests(APITestCase):
    def make_rom(self, **kwargs):
        user = make_user("uploader", "super_admin")
        return ROM.objects.create(
            title="Bomberman 64", platform="N64", file=dummy_rom("bomberman.z64"), uploaded_by=user, **kwargs
        )

    def scraped_filename(self, rom):
        with mock.patch("apps.roms.cover_art.scrape_cover_art", return_value=None) as scrape:
            scrape_rom(rom, BOTH_PROVIDERS)
        return scrape.call_args.args[2]

    def test_passes_original_filename_when_set(self):
        rom = self.make_rom(filename="Bomberman 64 (U) [!].z64")
        self.assertEqual(self.scraped_filename(rom), "Bomberman 64 (U) [!].z64")

    def test_falls_back_to_storage_name_when_blank(self):
        rom = self.make_rom()
        self.assertEqual(self.scraped_filename(rom), _without_dedup_suffix(rom.file.name))

    def test_original_filename_keeps_a_seven_char_tail(self):
        rom = self.make_rom(filename="Pokemon_Emerald.gba")
        filename = self.scraped_filename(rom)
        self.assertIn("Pokemon_Emerald", _title_candidates(rom.title, filename))

    def test_storage_name_loses_its_dedup_suffix(self):
        rom = self.make_rom()
        rom.file.name = "roms/zelda_OvlBGqX.gba"
        self.assertEqual(self.scraped_filename(rom), "roms/zelda.gba")


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

    def test_upload_succeeds_when_enqueue_fails(self):
        self.client.force_authenticate(self.admin_user)
        with mock.patch("apps.roms.views.scrape_rom_cover", side_effect=ConnectionError("redis down")), self.assertLogs(
            "apps.roms.views", "ERROR"
        ):
            response = self.client.post(self.list_url, {"title": "Metroid", "file": dummy_rom()}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ROM.objects.count(), 1)

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


class SweepMissingCoverArtTests(TestCase):
    def test_sweep_enqueues_only_missing(self):
        admin_user = make_user("admin", "super_admin")
        missing_a = ROM.objects.create(title="Metroid", file=dummy_rom("metroid.nes"), uploaded_by=admin_user)
        missing_b = ROM.objects.create(title="Kid Icarus", file=dummy_rom("icarus.nes"), uploaded_by=admin_user)
        covered = ROM.objects.create(title="Zelda", file=dummy_rom("zelda.nes"), uploaded_by=admin_user)
        covered.cover_art.save("zelda.png", ContentFile(b"art"), save=True)

        with mock.patch("birdroms.tasks.scrape_rom_cover") as scrape:
            sweep_missing_cover_art.call_local()

        self.assertEqual({call.args[0] for call in scrape.call_args_list}, {missing_a.pk, missing_b.pk})
        self.assertEqual(scrape.call_count, 2)


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

    def test_download_uses_original_filename(self):
        self.rom.title = "Bomberman 64"
        self.rom.filename = "Bomberman 64 (U) [!].z64"
        self.rom.save()
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(self.url)
        self.assertIn('filename="Bomberman 64 (U) [!].z64"', response["Content-Disposition"])

    def test_download_original_filename_is_sanitized(self):
        self.rom.filename = "Evil\r\nGame/x\\y.nes"
        self.rom.save()
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(self.url)
        self.assertIn('filename="EvilGame_x_y.nes"', response["Content-Disposition"])
        for value in response.headers.values():
            self.assertNotIn("\n", value)
            self.assertNotIn("\r", value)

    def test_unknown_id_returns_404(self):
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(reverse("rom-download", args=[self.rom.pk + 999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_stored_file_returns_404_not_500(self):
        # A row whose file is gone from storage (a lost media dir, a half-restored backup) is a missing
        # resource, not a server fault; clients such as the handheld rely on a clean 404.
        self.rom.file.delete(save=False)
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(self.url)
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


class DeviceListingTests(APITestCase):
    list_url = reverse("rom-list")
    platforms_url = reverse("rom-platforms")

    def setUp(self):
        self.admin_user = make_user("admin", "super_admin")
        self.client.force_authenticate(make_user("reader", "readonly"))

    def add(self, title, filename, **kwargs):
        return ROM.objects.create(title=title, file=dummy_rom(filename), uploaded_by=self.admin_user, **kwargs)

    def device_list(self, **params):
        return self.client.get(self.list_url, {"fields": "device", **params})

    def test_device_listing_has_size_and_cover_url(self):
        with_cover = self.add("Zelda", "zelda.nes", cover_art=ContentFile(b"png", name="zelda.png"))
        without_cover = self.add("Metroid", "metroid.nes")

        response = self.device_list()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = {row["id"]: row for row in response.data["results"]}
        self.assertEqual(set(rows[with_cover.pk]), {"id", "title", "platform", "extension", "size_bytes", "cover_url", "filename", "tags"})
        self.assertEqual(rows[with_cover.pk]["title"], "Zelda")
        self.assertEqual(rows[with_cover.pk]["platform"], "NES")
        self.assertEqual(rows[with_cover.pk]["extension"], ".nes")
        self.assertEqual(rows[with_cover.pk]["size_bytes"], 16)
        self.assertTrue(rows[with_cover.pk]["cover_url"].endswith(f"/api/roms/{with_cover.pk}/cover/"))
        self.assertIsNone(rows[without_cover.pk]["cover_url"])

    def test_default_listing_is_unchanged(self):
        self.add("Zelda", "zelda.nes")
        row = self.client.get(self.list_url).data["results"][0]
        self.assertIn("download_url", row)
        self.assertNotIn("size_bytes", row)

    def test_size_bytes_is_null_when_the_file_size_is_unavailable(self):
        self.add("Zelda", "zelda.nes")
        with mock.patch("django.db.models.fields.files.FieldFile.size", new_callable=mock.PropertyMock) as size:
            size.side_effect = OSError("storage unavailable")
            response = self.device_list()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["results"][0]["size_bytes"])

    def test_device_listing_paginates(self):
        for i in range(30):
            self.add(f"Game {i:02d}", f"game{i}.nes")

        first = self.device_list()
        self.assertEqual(set(first.data), {"count", "next", "previous", "results"})
        self.assertEqual(first.data["count"], 30)
        self.assertEqual(len(first.data["results"]), 24)
        self.assertIsNotNone(first.data["next"])
        self.assertIn("fields=device", first.data["next"])

        second = self.device_list(page=2)
        self.assertEqual(len(second.data["results"]), 6)
        self.assertEqual(len(self.device_list(page_size=5).data["results"]), 5)

    def test_device_listing_reuses_search_and_platform_filters(self):
        self.add("Zelda", "zelda.nes")
        self.add("Zelda Minish Cap", "minish.gba")
        self.add("Metroid Fusion", "fusion.gba")

        response = self.device_list(search="zelda", platform="Game Boy Advance")

        self.assertEqual([row["title"] for row in response.data["results"]], ["Zelda Minish Cap"])

    def test_device_listing_requires_a_role(self):
        self.client.force_authenticate(make_user("nobody"))
        self.assertEqual(self.device_list().status_code, status.HTTP_403_FORBIDDEN)

    def test_platforms_endpoint_returns_distinct_platforms_for_browse(self):
        self.add("Zelda", "zelda.nes")
        self.add("Metroid", "metroid.nes")
        self.add("Minish Cap", "minish.gba")

        self.assertEqual(self.client.get(self.platforms_url).data, ["Game Boy Advance", "NES"])


class ROMAdminTests(TestCase):
    changelist_url = "/admin/roms/rom/"

    def test_filename_and_tags_are_read_only_and_filename_searchable(self):
        model_admin = ROMAdmin(ROM, admin.site)
        readonly = model_admin.get_readonly_fields(None)
        self.assertIn("filename", readonly)
        self.assertIn("tags", readonly)
        self.assertIn("filename", model_admin.search_fields)

    def setUp(self):
        self.superuser = User.objects.create_superuser("root", "root@example.com", "test-pass-123")
        self.client.force_login(self.superuser)

    def make_rom(self, title, name, cover=False):
        rom = ROM.objects.create(title=title, file=dummy_rom(name), uploaded_by=self.superuser)
        if cover:
            rom.cover_art.save("cover.png", ContentFile(b"png"), save=True)
        return rom

    def test_admin_changelist_loads(self):
        with_cover = self.make_rom("Metroid", "metroid.nes", cover=True)
        without_cover = self.make_rom("Pokemon Emerald", "emerald.gba")

        response = self.client.get(self.changelist_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Metroid")
        self.assertContains(response, "Pokemon Emerald")
        self.assertContains(response, "NES")
        self.assertContains(response, "Game Boy Advance")
        self.assertContains(response, f'src="{reverse("rom-cover", args=[with_cover.pk])}"')
        self.assertNotContains(response, f'src="{reverse("rom-cover", args=[without_cover.pk])}"')

    def test_admin_changelist_filters_and_searches(self):
        self.make_rom("Metroid", "metroid.nes")
        self.make_rom("Pokemon Emerald", "emerald.gba")

        by_platform = self.client.get(self.changelist_url, {"platform": "NES"})
        by_title = self.client.get(self.changelist_url, {"q": "Emerald"})

        self.assertContains(by_platform, "Metroid")
        self.assertNotContains(by_platform, "Pokemon Emerald")
        self.assertContains(by_title, "Pokemon Emerald")
        self.assertNotContains(by_title, "Metroid")

    def test_admin_change_page_loads(self):
        rom = self.make_rom("Metroid", "metroid.nes", cover=True)
        response = self.client.get(f"{self.changelist_url}{rom.pk}/change/")
        self.assertEqual(response.status_code, 200)

    def test_admin_rescrape_action(self):
        first = self.make_rom("Metroid", "metroid.nes")
        second = self.make_rom("Zelda", "zelda.nes")
        self.make_rom("Kirby", "kirby.nes")

        with mock.patch("apps.roms.admin.scrape_rom_cover") as scrape:
            response = self.client.post(
                self.changelist_url,
                {"action": "rescrape_cover_art", "_selected_action": [first.pk, second.pk]},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual({call.args[0] for call in scrape.call_args_list}, {first.pk, second.pk})
        self.assertEqual(scrape.call_count, 2)
        self.assertContains(response, "Queued cover art scraping for 2 ROMs.")


    def test_admin_rescrape_action_survives_enqueue_failure(self):
        rom = self.make_rom("Metroid", "metroid.nes")
        with mock.patch("apps.roms.admin.scrape_rom_cover", side_effect=ConnectionError("redis down")), self.assertLogs(
            "apps.roms.admin", "ERROR"
        ):
            response = self.client.post(
                self.changelist_url,
                {"action": "rescrape_cover_art", "_selected_action": [rom.pk]},
                follow=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Could not queue cover art scraping for 1 ROM")
        self.assertContains(response, "Queued cover art scraping for 0 ROMs.")


class ImageUrlAllowlistTests(SimpleTestCase):
    """Cover images may only come from the providers' own HTTPS hosts (SSRF guard): the
    ScreenScraper payload is third-party data and must not steer requests elsewhere."""

    def test_provider_hosts_are_allowed(self):
        for url in (
            "https://thumbnails.libretro.com/NES/Named_Boxarts/Metroid.png",
            "https://screenscraper.fr/image.php?x=1",
            "https://www.screenscraper.fr/image.php",
            "https://api.screenscraper.fr/api2/mediaJeu.php",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_allowed_image_url(url))

    def test_everything_else_is_rejected(self):
        for url in (
            "http://thumbnails.libretro.com/x.png",  # not TLS
            "http://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1/x.png",
            "https://localhost:8000/api/roms/",
            "https://evil.example/x.png",
            "https://screenscraper.fr.evil.example/x.png",
            "https://notscreenscraper.fr/x.png",
            "https://screenscraper.fr@evil.example/x.png",
            "https://user:pw@screenscraper.fr/x.png",
            "https://screenscraper.fr:8443/x.png",
            "file:///etc/passwd",
            "ftp://screenscraper.fr/x.png",
            "//screenscraper.fr/x.png",
            "",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_allowed_image_url(url))

    def test_download_refuses_a_disallowed_url_without_requesting_it(self):
        with mock.patch("apps.roms.cover_art.requests.get") as get, self.assertLogs("apps.roms.cover_art", "WARNING"):
            self.assertIsNone(download_image("http://169.254.169.254/latest/meta-data/", LIBRETRO_ONLY))
        get.assert_not_called()

    def test_download_follows_redirects_only_to_allowed_hosts(self):
        start = "https://thumbnails.libretro.com/a.png"

        def redirect(target):
            return FakeResponse(status_code=302, content_type="text/html", headers={"Location": target})

        get = fake_http(
            {
                "mirror.screenscraper.fr/b.png": FakeResponse(content=PNG_BYTES),
                "thumbnails.libretro.com/a.png": redirect("https://mirror.screenscraper.fr/b.png"),
            }
        )
        with mock.patch("apps.roms.cover_art.requests.get", get):
            self.assertEqual(download_image(start, LIBRETRO_ONLY), (PNG_BYTES, ".png"))
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

        get = fake_http({"thumbnails.libretro.com/a.png": redirect("http://127.0.0.1:8000/admin/")})
        with mock.patch("apps.roms.cover_art.requests.get", get), self.assertLogs("apps.roms.cover_art", "WARNING"):
            self.assertIsNone(download_image(start, LIBRETRO_ONLY))
        self.assertEqual(get.call_count, 1)  # The internal target was never requested.

    def test_redirect_loops_are_cut_off(self):
        loop = FakeResponse(status_code=302, content_type="text/html", headers={"Location": "/a.png"})
        get = fake_http({"thumbnails.libretro.com": loop})
        with mock.patch("apps.roms.cover_art.requests.get", get):
            self.assertIsNone(download_image("https://thumbnails.libretro.com/a.png", LIBRETRO_ONLY))
        self.assertLessEqual(get.call_count, 5)


class SecretRedactionTests(SimpleTestCase):
    def test_redact_secrets_masks_credential_query_params(self):
        text = (
            "500 for url: https://api.screenscraper.fr/api2/jeuInfos.php"
            "?devid=dev&devpassword=DEVSECRET1&ssid=me&sspassword=USERSECRET2&x=1"
        )
        redacted = redact_secrets(text)
        for secret in ("DEVSECRET1", "USERSECRET2", "devid=dev&", "ssid=me"):
            self.assertNotIn(secret, redacted)
        self.assertIn("x=1", redacted)

    def test_provider_failures_never_log_credentials(self):
        url = "https://api.screenscraper.fr/api2/jeuInfos.php?devid=dev&devpassword=DEVSECRET1&ssid=me&sspassword=USERSECRET2"
        get = fake_http({"screenscraper.fr": requests.ConnectionError(f"Max retries exceeded with url: {url}")})
        with mock.patch("apps.roms.cover_art.requests.get", get), self.assertLogs(
            "apps.roms.cover_art", "WARNING"
        ) as logs:
            self.assertIsNone(scrape_cover_art("Metroid", "NES", "metroid.nes", BOTH_PROVIDERS))
        output = "\n".join(logs.output)
        self.assertNotIn("DEVSECRET1", output)
        self.assertNotIn("USERSECRET2", output)

    def test_screenscraper_lookup_failures_never_log_credentials(self):
        url = "https://api.screenscraper.fr/api2/jeuInfos.php?devpassword=DEVSECRET1&sspassword=USERSECRET2"
        get = fake_http({"screenscraper.fr": requests.ConnectionError(url)})
        config = parse_cover_art_settings({**BOTH_PROVIDERS_ENV, "COVER_ART_PROVIDERS": "screenscraper"})
        with mock.patch("apps.roms.cover_art.requests.get", get), self.assertLogs(
            "apps.roms.cover_art", "WARNING"
        ) as logs:
            self.assertIsNone(ScreenScraperGame("Metroid", "NES", "metroid.nes", config).jeu)
        output = "\n".join(logs.output)
        self.assertNotIn("DEVSECRET1", output)
        self.assertNotIn("USERSECRET2", output)


class MediaAccessControlTests(APITestCase):
    """ROM files and cover art are private: only authenticated users with a role may fetch them."""

    def setUp(self):
        self.admin = make_user("admin", "super_admin")
        self.rom = ROM.objects.create(title="Zelda", file=dummy_rom("zelda.nes"), uploaded_by=self.admin)
        self.rom.cover_art.save("rom-1.png", ContentFile(PNG_BYTES), save=True)

    def test_anonymous_and_roleless_users_cannot_fetch_files_or_covers(self):
        for name in ("rom-download", "rom-cover", "rom-detail"):
            url = reverse(name, args=[self.rom.pk])
            with self.subTest(name=name, who="anonymous"):
                self.assertIn(self.client.get(url).status_code, (401, 403))
        self.client.force_authenticate(make_user("nobody"))
        for name in ("rom-download", "rom-cover", "rom-detail"):
            with self.subTest(name=name, who="roleless"):
                self.assertEqual(self.client.get(reverse(name, args=[self.rom.pk])).status_code, 403)

    def test_readonly_users_cannot_modify_delete_or_scrape(self):
        # Uploading (create) is open to any authenticated user; every other write stays super_admin-only.
        self.client.force_authenticate(make_user("reader", "readonly"))
        detail = reverse("rom-detail", args=[self.rom.pk])
        self.assertEqual(self.client.post(reverse("rom-scrape-cover", args=[self.rom.pk])).status_code, 403)
        self.assertEqual(self.client.patch(detail, {"title": "X"}).status_code, 403)
        self.assertEqual(self.client.delete(detail).status_code, 403)
        self.rom.refresh_from_db()
        self.assertEqual(self.rom.title, "Zelda")

    def test_cover_is_served_as_an_image_with_nosniff(self):
        self.client.force_authenticate(make_user("reader", "readonly"))
        response = self.client.get(reverse("rom-cover", args=[self.rom.pk]))
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")


class HostileInputTests(APITestCase):
    def setUp(self):
        self.admin = make_user("admin", "super_admin")
        self.client.force_authenticate(self.admin)

    def test_upload_filename_cannot_escape_the_roms_directory(self):
        for name in ("../../evil.nes", "/etc/cron.d/evil.nes", "..\\..\\evil.nes"):
            with self.subTest(name=name):
                response = self.client.post(
                    reverse("rom-list"), {"title": "x", "file": dummy_rom(name)}, format="multipart"
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                stored = ROM.objects.latest("id").file.name
                self.assertTrue(stored.startswith("roms/"), stored)
                self.assertNotIn("..", stored)
                self.assertNotIn("//", stored)

    def test_download_filename_drops_control_characters(self):
        rom = ROM.objects.create(title="Evil\r\nSet-Cookie: x=1", file=dummy_rom("a.nes"), uploaded_by=self.admin)
        response = self.client.get(reverse("rom-download", args=[rom.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for value in response.headers.values():
            self.assertNotIn("\n", value)
            self.assertNotIn("\r", value)


class PlaylistTests(APITestCase):
    list_url = reverse("playlist-list")

    def setUp(self):
        self.owner = make_user("owner")
        self.other = make_user("other")
        self.rom_a = ROM.objects.create(title="A", file=dummy_rom("a.nes"), uploaded_by=self.owner)
        self.rom_b = ROM.objects.create(title="B", file=dummy_rom("b.nes"), uploaded_by=self.owner)
        self.rom_c = ROM.objects.create(title="C", file=dummy_rom("c.nes"), uploaded_by=self.owner)

    def make_playlist(self, *roms):
        playlist = Playlist.objects.create(name="Road trip", created_by=self.owner)
        for order, rom in enumerate(roms):
            PlaylistItem.objects.create(playlist=playlist, rom=rom, order=order)
        return playlist

    def test_anonymous_cannot_list_or_create(self):
        self.assertIn(self.client.get(self.list_url).status_code, (401, 403))
        self.assertIn(self.client.post(self.list_url, {"name": "x"}).status_code, (401, 403))

    def test_any_authed_user_creates_playlist(self):
        # No role group is needed: playlists are open to every authenticated user.
        self.client.force_authenticate(self.other)

        response = self.client.post(
            self.list_url, {"name": "Mine", "rom_ids": [self.rom_b.pk, self.rom_a.pk]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        playlist = Playlist.objects.get(pk=response.data["id"])
        self.assertEqual(playlist.created_by, self.other)
        self.assertEqual(response.data["created_by"], self.other.pk)
        self.assertEqual(response.data["created_by_username"], "other")
        self.assertEqual([rom["id"] for rom in response.data["roms"]], [self.rom_b.pk, self.rom_a.pk])

    def test_create_ignores_client_supplied_owner(self):
        self.client.force_authenticate(self.other)
        response = self.client.post(self.list_url, {"name": "Mine", "created_by": self.owner.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Playlist.objects.get().created_by, self.other)

    def test_create_rejects_unknown_and_duplicate_roms(self):
        self.client.force_authenticate(self.other)
        unknown = self.client.post(self.list_url, {"name": "x", "rom_ids": [999999]}, format="json")
        duplicate = self.client.post(self.list_url, {"name": "x", "rom_ids": [self.rom_a.pk, self.rom_a.pk]}, format="json")
        self.assertEqual(unknown.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Playlist.objects.count(), 0)

    def test_create_rejects_an_overlong_rom_ids_list(self):
        self.client.force_authenticate(self.other)
        response = self.client.post(self.list_url, {"name": "x", "rom_ids": list(range(1, 502))}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rom_ids", response.data)
        self.assertEqual(Playlist.objects.count(), 0)

    def test_create_requires_a_name(self):
        self.client.force_authenticate(self.other)
        response = self.client.post(self.list_url, {"name": ""}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_shows_every_users_playlists(self):
        self.make_playlist(self.rom_a, self.rom_b)
        self.client.force_authenticate(self.other)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([p["name"] for p in response.data], ["Road trip"])
        self.assertEqual(response.data[0]["rom_count"], 2)

    def test_playlist_list_is_lightweight(self):
        # The list is unpaginated, so it must not carry every ROM of every playlist.
        self.make_playlist(self.rom_a, self.rom_b)
        self.client.force_authenticate(self.other)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data[0]), {"id", "name", "created_by", "created_at", "rom_count"})
        self.assertEqual(response.data[0]["rom_count"], 2)
        self.assertNotIn("roms", response.data[0])

    def test_playlist_detail_returns_ordered_roms(self):
        # Insert out of id order so ordering can only come from `order`.
        playlist = self.make_playlist(self.rom_c, self.rom_a, self.rom_b)
        self.client.force_authenticate(self.other)

        response = self.client.get(reverse("playlist-detail", args=[playlist.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([rom["id"] for rom in response.data["roms"]], [self.rom_c.pk, self.rom_a.pk, self.rom_b.pk])

    def test_playlist_detail_roms_have_size_bytes(self):
        covered = ROM.objects.create(
            title="D", file=dummy_rom("d.nes"), uploaded_by=self.owner, cover_art=ContentFile(b"png", name="d.png")
        )
        playlist = self.make_playlist(covered, self.rom_a)
        self.client.force_authenticate(self.other)

        response = self.client.get(reverse("playlist-detail", args=[playlist.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        first, second = response.data["roms"]
        self.assertEqual([first["id"], second["id"]], [covered.pk, self.rom_a.pk])
        device_shape = {"id", "title", "platform", "extension", "size_bytes", "cover_url", "filename", "tags"}
        self.assertEqual(set(first), device_shape)
        self.assertEqual(set(second), device_shape)
        self.assertEqual(first["size_bytes"], 16)
        self.assertTrue(first["cover_url"].endswith(f"/api/roms/{covered.pk}/cover/"))
        self.assertIsNone(second["cover_url"])
        # Heavy full-ROM fields are gone; the device downloads via the ROM endpoint by id.
        self.assertNotIn("download_url", first)

    def test_non_owner_cannot_edit_others_playlist(self):
        playlist = self.make_playlist(self.rom_a)
        url = reverse("playlist-detail", args=[playlist.pk])
        self.client.force_authenticate(self.other)

        self.assertEqual(self.client.patch(url, {"name": "Hijacked"}, format="json").status_code, 403)
        self.assertEqual(self.client.put(url, {"name": "Hijacked"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(url).status_code, 403)

        playlist.refresh_from_db()
        self.assertEqual(playlist.name, "Road trip")
        self.assertEqual(playlist.items.count(), 1)

    def test_owner_can_rename_reorder_and_delete(self):
        playlist = self.make_playlist(self.rom_a, self.rom_b)
        url = reverse("playlist-detail", args=[playlist.pk])
        self.client.force_authenticate(self.owner)

        response = self.client.patch(
            url, {"name": "Renamed", "rom_ids": [self.rom_c.pk, self.rom_b.pk]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Renamed")
        self.assertEqual([rom["id"] for rom in response.data["roms"]], [self.rom_c.pk, self.rom_b.pk])

        # A rename alone leaves the items untouched.
        response = self.client.patch(url, {"name": "Again"}, format="json")
        self.assertEqual([rom["id"] for rom in response.data["roms"]], [self.rom_c.pk, self.rom_b.pk])

        self.assertEqual(self.client.delete(url).status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Playlist.objects.exists())
        self.assertEqual(ROM.objects.count(), 3)

    def test_deleting_a_rom_drops_it_from_playlists(self):
        playlist = self.make_playlist(self.rom_a, self.rom_b)
        self.rom_a.delete()
        self.client.force_authenticate(self.owner)

        response = self.client.get(reverse("playlist-detail", args=[playlist.pk]))

        self.assertEqual([rom["id"] for rom in response.data["roms"]], [self.rom_b.pk])


class FilenameAndTagsTests(APITestCase):
    list_url = reverse("rom-list")
    NAME = "Bomberman 64 (U) [!].z64"

    def setUp(self):
        self.admin = make_user("admin", "super_admin")
        self.client.force_authenticate(self.admin)

    def upload(self, name=NAME, **extra):
        return self.client.post(self.list_url, {"file": dummy_rom(name), **extra}, format="multipart")

    def test_upload_without_title_derives_title_filename_and_tags(self):
        response = self.upload()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Bomberman 64")
        self.assertEqual(response.data["filename"], self.NAME)
        self.assertEqual(response.data["tags"], ["USA", "Verified good dump"])
        rom = ROM.objects.get()
        self.assertEqual((rom.filename, rom.tags), (self.NAME, ["USA", "Verified good dump"]))

    def test_supplied_title_is_kept(self):
        response = self.upload(title="  My Name ")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "My Name")
        self.assertEqual(response.data["filename"], self.NAME)
        self.assertEqual(response.data["tags"], ["USA", "Verified good dump"])

    def test_blank_title_is_derived(self):
        response = self.upload(title="   ")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Bomberman 64")

    def test_filename_is_sanitized_and_truncated_keeping_extension(self):
        long_name = "a" * 300 + ".nes"
        response = self.upload(long_name)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["filename"]), 255)
        self.assertTrue(response.data["filename"].endswith(".nes"))
        self.assertLessEqual(len(response.data["title"]), 255)

    def test_filename_drops_control_characters(self):
        response = self.upload("a\x01b.nes")

        self.assertEqual(response.data["filename"], "ab.nes")

    def test_patch_changes_only_the_title(self):
        rom_id = self.upload().data["id"]
        url = reverse("rom-detail", args=[rom_id])

        response = self.client.patch(url, {"title": "Renamed", "filename": "x.z64", "tags": ["Hacked"]}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rom = ROM.objects.get(pk=rom_id)
        self.assertEqual(rom.title, "Renamed")
        self.assertEqual(rom.filename, self.NAME)
        self.assertEqual(rom.tags, ["USA", "Verified good dump"])

    def test_blank_title_is_rejected_when_editing(self):
        rom_id = self.upload().data["id"]
        url = reverse("rom-detail", args=[rom_id])

        response = self.client.patch(url, {"title": ""}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ROM.objects.get(pk=rom_id).title, "Bomberman 64")

    def test_device_listing_includes_filename_and_tags(self):
        self.upload()

        response = self.client.get(self.list_url, {"fields": "device"})

        row = response.data["results"][0]
        self.assertEqual(row["filename"], self.NAME)
        self.assertEqual(row["tags"], ["USA", "Verified good dump"])

    def test_playlist_detail_includes_filename_and_tags(self):
        rom_id = self.upload().data["id"]
        playlist = Playlist.objects.create(name="P", created_by=self.admin)
        PlaylistItem.objects.create(playlist=playlist, rom_id=rom_id, order=0)

        response = self.client.get(reverse("playlist-detail", args=[playlist.pk]))

        self.assertEqual(response.data["roms"][0]["filename"], self.NAME)
        self.assertEqual(response.data["roms"][0]["tags"], ["USA", "Verified good dump"])

    def test_search_matches_the_filename(self):
        self.upload()

        response = self.client.get(self.list_url, {"search": "(U)"})

        self.assertEqual(response.data["count"], 1)


class BackfillMigrationTests(TestCase):
    def setUp(self):
        self.user = make_user("backfiller", "super_admin")
        migration = importlib.import_module("apps.roms.migrations.0006_backfill_rom_filenames")
        self.backfill = migration.backfill
        self.restore = migration.restore

    def legacy_rom(self, title, stored_name):
        return ROM.objects.create(title=title, file=dummy_rom(stored_name), uploaded_by=self.user, filename="")

    def test_backfill_cleans_title_when_title_already_has_extension(self):
        rom = self.legacy_rom("6111 - Pokemon Black 2 (US) (frieNDS).nds", "pokemon.nds")

        self.backfill(django_apps, None)

        rom.refresh_from_db()
        self.assertEqual(rom.filename, "6111 - Pokemon Black 2 (US) (frieNDS).nds")
        self.assertEqual(rom.title, "Pokemon Black 2")
        self.assertEqual(rom.tags, ["USA", "frieNDS"])

    def test_backfill_appends_extension_when_title_lacks_it(self):
        rom = self.legacy_rom("Bomberman 64 (U) [!]", "bomberman.z64")

        self.backfill(django_apps, None)

        rom.refresh_from_db()
        self.assertEqual(rom.filename, "Bomberman 64 (U) [!].z64")
        self.assertEqual(rom.title, "Bomberman 64")

    def test_backfill_leaves_rows_with_a_filename_untouched(self):
        rom = ROM.objects.create(
            title="Kept", file=dummy_rom("kept.gba"), uploaded_by=self.user, filename="Kept (U).gba", tags=["x"]
        )

        self.backfill(django_apps, None)

        rom.refresh_from_db()
        self.assertEqual((rom.title, rom.filename, rom.tags), ("Kept", "Kept (U).gba", ["x"]))

    def test_backfill_long_title_keeps_the_extension(self):
        rom = self.legacy_rom("a" * 254, "long.gba")

        self.backfill(django_apps, None)

        rom.refresh_from_db()
        self.assertEqual(len(rom.filename), 255)
        self.assertTrue(rom.filename.endswith(".gba"))

    def test_restore_puts_the_filename_back_in_the_title(self):
        rom = self.legacy_rom("Bomberman 64 (U) [!]", "bomberman.z64")
        self.backfill(django_apps, None)

        self.restore(django_apps, None)

        rom.refresh_from_db()
        self.assertEqual(rom.title, "Bomberman 64 (U) [!].z64")
        self.assertEqual(rom.filename, "")
        self.assertEqual(rom.tags, [])
