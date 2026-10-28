import io
from contextlib import nullcontext
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings

from PIL import Image

from apps.roms.cover_art import scrape_rom
from apps.roms.library import LibraryUnavailable
from apps.roms.test_library_api import LibraryRootTestCase
from birdroms.library_config import parse_library_settings

IMG = "ROMS/SFC/Imgs/Game (USA).png"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def image_bytes(fmt="JPEG", mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, (4, 4)).save(buf, fmt)
    return buf.getvalue()


def provider(data, extension=".jpg"):
    """Patch the provider lookup so `scrape_rom` finds `data` as the cover."""
    return mock.patch(
        "apps.roms.cover_art.scrape_cover_art", return_value=(data, extension, SimpleNamespace(source="libretro"))
    )


class CoverWritebackTests(LibraryRootTestCase):
    def setUp(self):
        super().setUp()
        self.rom = self.library_rom()

    def scrape(self, data=None, extension=".jpg"):
        with provider(image_bytes() if data is None else data, extension):
            self.assertEqual(scrape_rom(self.rom), (True, False))
        self.rom.refresh_from_db()

    def test_cover_is_written_as_png_and_linked(self):
        self.scrape()
        written = (self.root / IMG).read_bytes()
        self.assertTrue(written.startswith(PNG_SIGNATURE))
        self.assertEqual(Image.open(io.BytesIO(written)).format, "PNG")
        self.assertEqual(self.rom.cover_path, IMG)
        self.assertTrue(self.rom.cover_art)

    def test_png_source_is_written_unchanged(self):
        png = image_bytes("PNG")
        self.scrape(png, ".png")
        self.assertEqual((self.root / IMG).read_bytes(), png)

    def test_palette_and_alpha_modes_convert(self):
        for fmt, mode in (("GIF", "P"), ("WEBP", "RGBA")):
            with self.subTest(fmt=fmt):
                (self.root / IMG).unlink(missing_ok=True)
                self.scrape(image_bytes(fmt, mode), ".img")
                self.assertEqual(Image.open(self.root / IMG).format, "PNG")

    def test_existing_png_is_linked_not_overwritten(self):
        self.put(IMG, b"existing")
        self.scrape()
        self.assertEqual((self.root / IMG).read_bytes(), b"existing")
        self.assertEqual(self.rom.cover_path, IMG)
        self.assertTrue(self.rom.cover_art)

    def test_write_covers_off_writes_nothing(self):
        library = parse_library_settings({"LIBRARY_ROOT": str(self.root), "LIBRARY_WRITE_COVERS": "false"})
        with override_settings(LIBRARY=library):
            self.scrape()
        self.assertFalse((self.root / IMG).exists())
        self.assertEqual(self.rom.cover_path, "")
        self.assertTrue(self.rom.cover_art)

    def test_read_only_library_writes_nothing(self):
        library = parse_library_settings({"LIBRARY_ROOT": str(self.root), "LIBRARY_READ_ONLY": "true"})
        with override_settings(LIBRARY=library):
            self.scrape()
        self.assertFalse((self.root / IMG).exists())
        self.assertEqual(self.rom.cover_path, "")
        self.assertTrue(self.rom.cover_art)

    def test_failures_keep_the_media_cover(self):
        write = "apps.roms.library.FilesystemLibrary.write_new"
        cases = {
            "bad image": (b"not an image", None),
            "write error": (None, OSError("disk full")),
            "unavailable": (None, LibraryUnavailable("share down")),
        }
        for name, (data, error) in cases.items():
            with self.subTest(name), mock.patch(write, side_effect=error) if error else nullcontext():
                with self.assertLogs("apps.roms.cover_art", "WARNING"):
                    self.scrape(data)
                self.assertFalse((self.root / IMG).exists())
                self.assertEqual(self.rom.cover_path, "")
                self.assertTrue(self.rom.cover_art)
