import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.roms.handheld import InvalidMuxapp, handheld_info, personalized_package, validate_muxapp
from apps.roms.tests import make_user


def build_muxapp(path, names=("birdROMs/birdroms", "birdROMs/mux_launch.sh", "birdROMs/mux_lang.ini")):
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"x")
    return Path(path)


class TempHandheldCase:
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="birdroms-test-handheld-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.target = self.tmp / "published" / "birdROMs.muxapp"
        override = override_settings(HANDHELD_APP_PATH=self.target)
        override.enable()
        self.addCleanup(override.disable)


class ValidateMuxappTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="birdroms-test-handheld-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_accepts_a_birdroms_package(self):
        validate_muxapp(build_muxapp(self.tmp / "ok.muxapp"))

    def test_rejects_a_file_that_is_not_a_zip(self):
        path = self.tmp / "bad.muxapp"
        path.write_bytes(b"not a zip")
        with self.assertRaisesMessage(InvalidMuxapp, "zip"):
            validate_muxapp(path)

    def test_rejects_a_zip_missing_the_launcher(self):
        path = build_muxapp(self.tmp / "x.muxapp", names=("birdROMs/birdroms",))
        with self.assertRaisesMessage(InvalidMuxapp, "birdROMs/mux_launch.sh"):
            validate_muxapp(path)

    def test_rejects_a_package_not_rooted_at_birdroms(self):
        path = build_muxapp(self.tmp / "x.muxapp", names=("application/birdROMs/birdroms", "application/birdROMs/mux_launch.sh"))
        with self.assertRaises(InvalidMuxapp):
            validate_muxapp(path)


class HandheldInfoApiTests(TempHandheldCase, APITestCase):
    def test_requires_sign_in(self):
        self.assertEqual(self.client.get(reverse("handheld-info")).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.client.get(reverse("handheld-download")).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reports_unavailable_when_nothing_is_published(self):
        self.client.force_authenticate(make_user("reader", "readonly"))
        response = self.client.get(reverse("handheld-info"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"available": False})
        self.assertEqual(self.client.get(reverse("handheld-download")).status_code, status.HTTP_404_NOT_FOUND)

    def test_reports_the_published_package(self):
        self.target.parent.mkdir(parents=True)
        build_muxapp(self.target)
        self.client.force_authenticate(make_user("reader", "readonly"))
        data = self.client.get(reverse("handheld-info")).json()
        self.assertTrue(data["available"])
        self.assertEqual(data["filename"], "birdROMs.muxapp")
        self.assertEqual(data["size"], self.target.stat().st_size)
        self.assertNotIn("sha256", data)
        self.assertIn("published_at", data)
        self.assertNotIn(str(self.tmp), str(data))

    def test_download_streams_the_file_as_an_attachment(self):
        self.target.parent.mkdir(parents=True)
        build_muxapp(self.target)
        self.client.force_authenticate(make_user("reader", "readonly"))
        response = self.client.get(reverse("handheld-download"))
        self.assertEqual(response.status_code, 200)
        self.assertIn('filename="birdROMs.muxapp"', response["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
            names = set(archive.namelist())
            seed = json.loads(archive.read("birdROMs/server.json"))
        self.assertEqual(names, {"birdROMs/birdroms", "birdROMs/mux_launch.sh", "birdROMs/mux_lang.ini", "birdROMs/server.json"})
        self.assertEqual(seed, {"server_url": "http://testserver"})


class PersonalizedPackageTests(TempHandheldCase, SimpleTestCase):
    def test_replaces_an_existing_seed_and_keeps_other_entries(self):
        self.target.parent.mkdir(parents=True)
        build_muxapp(self.target, names=("birdROMs/birdroms", "birdROMs/mux_launch.sh", "birdROMs/server.json"))
        with personalized_package("https://birds.example/") as package:
            with zipfile.ZipFile(package) as archive:
                self.assertEqual(sorted(archive.namelist()), ["birdROMs/birdroms", "birdROMs/mux_launch.sh", "birdROMs/server.json"])
                self.assertEqual(json.loads(archive.read("birdROMs/server.json")), {"server_url": "https://birds.example"})
                self.assertEqual(archive.read("birdROMs/birdroms"), b"x")


class HandheldInfoUnitTests(TempHandheldCase, SimpleTestCase):
    def test_info_is_none_without_a_file(self):
        self.assertIsNone(handheld_info())


class PublishHandheldCommandTests(TempHandheldCase, SimpleTestCase):
    def test_publishes_a_valid_package(self):
        source = build_muxapp(self.tmp / "dist.muxapp")
        out = io.StringIO()
        call_command("publish_handheld", str(source), stdout=out)
        self.assertEqual(self.target.read_bytes(), source.read_bytes())
        self.assertIn("Published", out.getvalue())

    def test_replaces_a_previous_version(self):
        call_command("publish_handheld", str(build_muxapp(self.tmp / "a.muxapp")), stdout=io.StringIO())
        newer = build_muxapp(self.tmp / "b.muxapp", names=("birdROMs/birdroms", "birdROMs/mux_launch.sh", "birdROMs/extra"))
        call_command("publish_handheld", str(newer), stdout=io.StringIO())
        self.assertEqual(self.target.read_bytes(), newer.read_bytes())

    def test_refuses_an_invalid_package_and_keeps_the_old_one(self):
        good = build_muxapp(self.tmp / "good.muxapp")
        call_command("publish_handheld", str(good), stdout=io.StringIO())
        bad = self.tmp / "bad.muxapp"
        bad.write_bytes(b"nope")
        with self.assertRaises(CommandError):
            call_command("publish_handheld", str(bad), stdout=io.StringIO())
        self.assertEqual(self.target.read_bytes(), good.read_bytes())

    def test_refuses_a_missing_file(self):
        with self.assertRaises(CommandError):
            call_command("publish_handheld", str(self.tmp / "nope.muxapp"), stdout=io.StringIO())
