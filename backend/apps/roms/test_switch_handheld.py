"""Switch distribution is isolated from the existing muOS package contract."""
import hashlib
import io
import json
import stat
import warnings
import zipfile
from pathlib import Path

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


def build_switch(path, extra=(), metadata=None, nro=NRO):
    manifest = {"platform": "switch", "version": VERSION, "nro_sha256": hashlib.sha256(nro).hexdigest(), "nro_size": len(nro)}
    if metadata:
        manifest.update(metadata)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w") as archive:
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
