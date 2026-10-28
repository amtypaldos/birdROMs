from django.test import SimpleTestCase

from apps.roms import platform_aliases as pa
from apps.roms.platform_aliases import (
    UNSORTED_FOLDER,
    muos_folder_for,
    platform_for_folder,
    platform_for_game,
)

HANDHELD_NAMES = [
    "NES", "SNES", "Nintendo 64", "Game Boy", "Game Boy Color",
    "Game Boy Advance", "Nintendo DS", "Sega Master System", "Sega Genesis",
    "Sega Game Gear", "Sega 32X", "Sega Dreamcast", "Sony PlayStation",
    "Sony PSP", "PC Engine / TurboGrafx-16", "Neo Geo Pocket",
    "Neo Geo Pocket Color", "WonderSwan", "WonderSwan Color", "Atari 2600",
    "Atari 7800", "Atari Lynx",
]  # fmt: skip


class PlatformForFolderTests(SimpleTestCase):
    def test_muos_folder_and_aliases_resolve(self):
        for folder in ("SFC", "snes", "SNES"):
            self.assertEqual(platform_for_folder(folder).name, "SNES")

    def test_alias_names(self):
        self.assertEqual(platform_for_folder("megadrive").name, "Sega Genesis")
        self.assertEqual(platform_for_folder("MDCD").name, "Sega CD / Mega-CD")
        self.assertEqual(platform_for_folder("PICO").name, "PICO-8")

    def test_non_game_kind(self):
        self.assertEqual(platform_for_folder("PORTS").kind, "non-game")

    def test_unknown_is_none(self):
        self.assertIsNone(platform_for_folder("nope"))

    def test_bare_number_follows_csv(self):
        listed = "64" in pa._load()[0]
        self.assertEqual(platform_for_folder("64") is not None, listed)

    def test_whitespace_is_stripped(self):
        self.assertEqual(platform_for_folder("  sfc ").name, "SNES")


class PlatformForGameTests(SimpleTestCase):
    def test_ngp_extension_split(self):
        self.assertEqual(platform_for_game("NGP", "x.ngc").name, "Neo Geo Pocket Color")
        self.assertEqual(platform_for_game("NGP", "x.ngp").name, "Neo Geo Pocket")

    def test_ws_extension_split(self):
        self.assertEqual(platform_for_game("WS", "x.wsc").name, "WonderSwan Color")
        self.assertEqual(platform_for_game("WS", "x.ws").name, "WonderSwan")

    def test_non_game_folder_is_none(self):
        self.assertIsNone(platform_for_game("APPS", "a.sh"))

    def test_unknown_folder_is_none(self):
        self.assertIsNone(platform_for_game("nope", "a.bin"))

    def test_plain_folder(self):
        self.assertEqual(platform_for_game("SFC", "a.sfc").name, "SNES")


class MuosFolderForTests(SimpleTestCase):
    def test_known(self):
        self.assertEqual(muos_folder_for("SNES"), "SFC")
        self.assertEqual(muos_folder_for("Sega Genesis"), "MD")

    def test_unknown(self):
        self.assertIsNone(muos_folder_for("unknown-thing"))

    def test_handheld_names_are_canonical(self):
        for name in HANDHELD_NAMES:
            with self.subTest(name=name):
                self.assertTrue(muos_folder_for(name))

    def test_unsorted_constant(self):
        self.assertEqual(UNSORTED_FOLDER, "_UNSORTED")
