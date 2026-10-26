from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import ROM


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
