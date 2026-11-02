"""Switch distribution is isolated from the existing muOS package contract."""
import hashlib
import io
import json
import stat
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import DeviceToken
from apps.roms import handheld
from apps.roms.test_handheld import TempHandheldCase, build_muxapp
from apps.roms.tests import make_user

PREFIX = "switch/birdroms/"
NRO = b"\x00" * 16 + b"NRO0" + b"\x00" * 108
VERSION = "2026.11.01.2"


def build_switch(path, extra=(), metadata=None, nro=NRO, compression=zipfile.ZIP_STORED):
    manifest = {"platform": "switch", "version": VERSION, "nro_sha256": hashlib.sha256(nro).hexdigest(), "nro_size": len(nro)}
    if metadata:
        manifest.update(metadata)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            archive.writestr(PREFIX + "birdroms.nro", nro)
            archive.writestr(PREFIX + "version.json", json.dumps(manifest))
            for name, body in extra:
                archive.writestr(name, body)
    return Path(path)


class SwitchCase(TempHandheldCase):
    def setUp(self):
        super().setUp()
        self.switch_target = self.tmp / "published" / "birdROMs-switch.zip"
        override = override_settings(SWITCH_APP_PATH=self.switch_target)
        override.enable()
        self.addCleanup(override.disable)


class SwitchPublishTests(SwitchCase, SimpleTestCase):
    def test_publish_and_metadata_are_separate_from_muos(self):
        source = build_switch(self.tmp / "switch.zip")
        call_command("publish_handheld", str(source), platform="switch", stdout=io.StringIO())
        info = handheld.handheld_info(platform="switch")
        self.assertEqual(info["platform"], "switch")
        self.assertEqual(info["version"], VERSION)
        self.assertEqual(info["filename"], "birdROMs-switch.zip")
        self.assertEqual(info["nro_size"], len(NRO))
        self.assertEqual(info["nro_sha256"], hashlib.sha256(NRO).hexdigest())
        self.assertEqual(info["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(info["size"], source.stat().st_size)
        self.assertIn("published_at", info)
        self.assertFalse(self.target.exists())

    def test_rejects_unsafe_or_inconsistent_archives_and_preserves_published(self):
        good = build_switch(self.tmp / "good.zip")
        call_command("publish_handheld", str(good), platform="switch", stdout=io.StringIO())
        cases = [
            {"extra": [("../escape", b"x")]},
            {"extra": [("/absolute", b"x")]},
            {"extra": [("switch\\birdroms\\escape", b"x")]},
            {"extra": [(PREFIX + "config.json", b'{"device_token":"secret"}')]},
            {"extra": [(PREFIX + "extra.txt", b"unexpected")]},
            {"extra": [(PREFIX + "version.json", b"{}") ]},
            {"extra": [(PREFIX + "server.json", b'{"server_url":"https://example.test","device_token":"secret"}')]},
            {"extra": [(PREFIX + "server.json", b'{"server_url":"https://user:password@example.test"}')]},
            {"extra": [(PREFIX + "server.json", b'{"server_url":"https://example.test/private"}')]},
            {"metadata": {"nro_sha256": "0" * 64}},
            {"metadata": {"nro_size": len(NRO) + 1}},
            {"metadata": {"nro_size": True}},
            {"metadata": {"version": "latest"}},
            {"metadata": {"platform": "muos"}},
            {"metadata": {"device_token": "secret"}},
            {"nro": b"invalid NRO executable"},
        ]
        link = zipfile.ZipInfo(PREFIX + "server.json")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases.append({"extra": [(link, b"/etc/passwd")]})
        for index, args in enumerate(cases):
            with self.subTest(case=index):
                bad = build_switch(self.tmp / f"bad-{index}.zip", **args)
                with self.assertRaises(CommandError):
                    call_command("publish_handheld", str(bad), platform="switch", stdout=io.StringIO())
                self.assertEqual(self.switch_target.read_bytes(), good.read_bytes())

    def test_accepts_public_seed_but_download_replaces_it(self):
        source = build_switch(self.tmp / "seed.zip", extra=[(PREFIX + "server.json", b'{"server_url":"https://public.example"}')])
        call_command("publish_handheld", str(source), platform="switch", stdout=io.StringIO())
        with handheld.personalized_package("https://selfhost.example/", platform="switch") as result:
            with zipfile.ZipFile(result) as archive:
                self.assertEqual(set(archive.namelist()), {PREFIX + "birdroms.nro", PREFIX + "version.json", PREFIX + "server.json"})
                self.assertEqual(json.loads(archive.read(PREFIX + "server.json")), {"server_url": "https://selfhost.example"})
                self.assertEqual(archive.read(PREFIX + "birdroms.nro"), NRO)

    def test_bundle_missing_is_noop_and_new_bundle_installs(self):
        self.assertFalse(handheld.install_bundled(self.tmp / "absent.zip", platform="switch"))
        source = build_switch(self.tmp / "bundled.zip")
        self.assertTrue(handheld.install_bundled(source, platform="switch"))
        self.assertFalse(handheld.install_bundled(source, platform="switch"))
        call_command("install_bundled_handheld", platform="switch", stdout=io.StringIO())


class SwitchNativeContractTests(SwitchCase, SimpleTestCase):
    def test_rejects_compression_methods_not_supported_by_native_minizip(self):
        for compression in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            with self.subTest(compression=compression):
                source = build_switch(self.tmp / f"method-{compression}.zip", compression=compression)
                with self.assertRaises(handheld.InvalidMuxapp):
                    handheld.validate_switch_package(source)

    def test_accepts_native_stored_and_deflated_methods(self):
        for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            with self.subTest(compression=compression):
                source = build_switch(self.tmp / f"method-{compression}.zip", compression=compression)
                self.assertEqual(handheld.validate_switch_package(source)["version"], VERSION)

    def test_rejects_directory_records_containing_data(self):
        source = build_switch(self.tmp / "directory-data.zip", extra=[("switch/", b"notempty")])
        with self.assertRaises(handheld.InvalidMuxapp):
            handheld.validate_switch_package(source)

    def test_revision_must_fit_native_unsigned_32_bit_integer(self):
        source = build_switch(self.tmp / "revision-overflow.zip", metadata={"version": "2026.11.01.4294967296"})
        with self.assertRaises(handheld.InvalidMuxapp):
            handheld.validate_switch_package(source)
        valid = build_switch(self.tmp / "revision-boundary.zip", metadata={"version": "2026.11.01.4294967295"})
        self.assertEqual(handheld.validate_switch_package(valid)["version"], "2026.11.01.4294967295")

    def test_release_year_must_match_native_minimum_2020(self):
        source = build_switch(self.tmp / "old-date.zip", metadata={"version": "2019.12.31"})
        with self.assertRaises(handheld.InvalidMuxapp):
            handheld.validate_switch_package(source)

    def test_nro_limit_matches_native_64_mib_limit(self):
        self.assertLessEqual(handheld.SWITCH_MAX_NRO_BYTES, 64 * 1024 * 1024)

    def test_rejects_stored_archive_larger_than_native_64_mib_limit(self):
        # A valid self-extracting ZIP prefix demonstrates that overall container size,
        # not merely uncompressed entry size, must be checked.
        source = self.tmp / "oversized-container.zip"
        with source.open("wb") as target:
            target.seek(64 * 1024 * 1024)
            target.write(b"x")
        with zipfile.ZipFile(source, "a") as archive:
            with zipfile.ZipFile(build_switch(self.tmp / "inner.zip")) as inner:
                for item in inner.infolist():
                    archive.writestr(item, inner.read(item))
        with self.assertRaises(handheld.InvalidMuxapp):
            handheld.validate_switch_package(source)

    def test_personalized_archive_cannot_exceed_native_zip_limit(self):
        source = build_switch(self.tmp / "source.zip")
        call_command("publish_handheld", str(source), platform="switch", stdout=io.StringIO())
        with handheld.personalized_package("https://selfhost.example/", platform="switch") as package:
            package.seek(0, 2)
            personalized_size = package.tell()
        self.assertGreater(personalized_size, source.stat().st_size)
        # Lower only the ZIP budget to reproduce the boundary without a 64 MiB fixture.
        with patch.object(handheld, "SWITCH_MAX_ZIP_BYTES", personalized_size - 1, create=True):
            with self.assertRaises(handheld.InvalidMuxapp):
                handheld.personalized_package("https://selfhost.example/", platform="switch")

    def test_publisher_reserves_space_for_generated_server_seed(self):
        source = build_switch(self.tmp / "seed-headroom.zip")
        with patch.object(handheld, "SWITCH_MAX_ZIP_BYTES", source.stat().st_size + 100):
            with self.assertRaises(CommandError):
                call_command("publish_handheld", str(source), platform="switch", stdout=io.StringIO())
        self.assertFalse(self.switch_target.exists())

    def test_final_personalized_output_has_its_own_size_guard(self):
        source = build_switch(self.tmp / "guard-source.zip")
        call_command("publish_handheld", str(source), platform="switch", stdout=io.StringIO())
        with handheld.personalized_package("https://selfhost.example/", platform="switch") as package:
            package.seek(0, 2)
            size = package.tell()
        # Exercise the final output check independently of publish-time headroom.
        with patch.object(handheld, "validate_switch_package", return_value={}), patch.object(handheld, "SWITCH_MAX_ZIP_BYTES", size - 1):
            with self.assertRaises(handheld.InvalidMuxapp):
                handheld.personalized_package("https://selfhost.example/", platform="switch")

    def test_oversized_personalized_seed_cannot_consume_reserved_headroom(self):
        source = build_switch(self.tmp / "seed-limit.zip")
        call_command("publish_handheld", str(source), platform="switch", stdout=io.StringIO())
        with self.assertRaises(handheld.InvalidMuxapp):
            handheld.personalized_package("https://" + "x" * 4096, platform="switch")

    def test_nro_entry_limit_is_enforced_before_hashing(self):
        source = build_switch(self.tmp / "entry-over-budget.zip", nro=NRO + b"x" * 1024)
        with patch.object(handheld, "SWITCH_MAX_NRO_BYTES", 1024):
            with self.assertRaises(handheld.InvalidMuxapp):
                handheld.validate_switch_package(source)


class SwitchApiTests(SwitchCase, APITestCase):
    def publish(self):
        source = build_switch(self.tmp / "source.zip")
        call_command("publish_handheld", str(source), platform="switch", stdout=io.StringIO())

    def test_requires_auth_for_both_switch_endpoints(self):
        for name in ("handheld-info", "handheld-download"):
            self.assertEqual(self.client.get(reverse(name), {"platform": "switch"}).status_code, 401)

    def test_unknown_platform_is_400_for_both_endpoints(self):
        self.client.force_authenticate(make_user("switch-reader", "readonly"))
        for name in ("handheld-info", "handheld-download"):
            self.assertEqual(self.client.get(reverse(name), {"platform": "bogus"}).status_code, 400)

    def test_unpublished_switch_does_not_fall_back_to_muos(self):
        self.target.parent.mkdir(parents=True)
        build_muxapp(self.target)
        self.client.force_authenticate(make_user("switch-reader", "readonly"))
        self.assertEqual(self.client.get(reverse("handheld-info"), {"platform": "switch"}).json(), {"available": False, "platform": "switch"})
        self.assertEqual(self.client.get(reverse("handheld-download"), {"platform": "switch"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("handheld-info")).json()["filename"], "birdROMs.muxapp")

    def test_session_and_device_auth_get_same_personalized_switch_archive(self):
        self.publish()
        user = make_user("switch-reader", "readonly")
        self.client.force_login(user)
        info = self.client.get(reverse("handheld-info"), {"platform": "switch"})
        self.assertEqual(info.status_code, 200)
        self.assertEqual(info.json()["version"], VERSION)
        self.client.logout()
        _, token = DeviceToken.mint(user)
        self.client.credentials(HTTP_AUTHORIZATION="Device " + token)
        response = self.client.get(reverse("handheld-download"), {"platform": "switch"}, HTTP_ACCEPT="application/zip", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('filename="birdROMs-switch.zip"', response["Content-Disposition"])
        data = b"".join(response.streaming_content)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(json.loads(archive.read(PREFIX + "server.json")), {"server_url": "https://testserver"})
            self.assertNotIn(token.encode(), b"".join(archive.read(name) for name in archive.namelist()))
            self.assertNotIn(PREFIX + "config.json", archive.namelist())
        self.assertEqual(info.json()["sha256"], hashlib.sha256(self.switch_target.read_bytes()).hexdigest())
