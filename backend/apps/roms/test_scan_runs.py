import datetime
import io

import psycopg2
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, override_settings

from apps.roms import scanner
from apps.roms.models import ROM, LibraryScan
from apps.roms.scanner import run_library_scan
from apps.roms.test_scanner import ScannerTestCase
from birdroms.huey_config import parse_scan_crontab
from birdroms.library_config import LibrarySettings

SMALL_GUARD = LibrarySettings(guard_ratio=0.25, guard_min=1)


class RunLibraryScanTests(ScannerTestCase):
    def run_scan(self, **kwargs):
        with override_settings(LIBRARY=SMALL_GUARD), mock.patch("birdroms.tasks.scrape_rom_cover") as scrape:
            scan = run_library_scan(library=self.library, **kwargs)
        return scan, scrape

    def test_records_an_ok_scan_with_counters(self):
        self.touch("ROMS/SFC/Super Mario World (U).smc")
        self.touch("ROMS/MD/Sonic.md")
        self.touch("ROMS/NOPE/thing.bin")
        scan, _ = self.run_scan()
        scan.refresh_from_db()
        self.assertEqual(scan.state, "ok")
        self.assertEqual(scan.added, 2)
        self.assertEqual(scan.unknown_folders, ["NOPE"])
        self.assertIsNotNone(scan.finished_at)
        self.assertFalse(scan.accept_removals)

    def test_records_an_aborted_scan_with_the_reason(self):
        scan, scrape = self.run_scan()  # empty library
        self.assertEqual(scan.state, "aborted")
        self.assertTrue(scan.message)
        self.assertIsNotNone(scan.finished_at)
        scrape.assert_not_called()

    def test_records_accept_removals(self):
        self.touch("ROMS/MD/Sonic.md")
        scan, _ = self.run_scan(accept_removals=True)
        self.assertTrue(scan.accept_removals)

    def test_a_raising_scan_is_recorded_failed_and_releases_the_lock(self):
        self.touch("ROMS/MD/Sonic.md")
        with (
            override_settings(LIBRARY=SMALL_GUARD),
            mock.patch("apps.roms.scanner.scan_library", side_effect=RuntimeError("boom")),
            mock.patch.object(scanner, "_release_scan_lock", wraps=scanner._release_scan_lock) as release,
        ):
            scan = run_library_scan(library=self.library)
        self.assertEqual(scan.state, "failed")
        self.assertIn("boom", scan.message)
        self.assertIsNotNone(scan.finished_at)
        self.assertFalse(LibraryScan.objects.filter(state="running").exists())
        release.assert_called_once()

    def test_busy_lock_returns_none_and_writes_no_row(self):
        self.touch("ROMS/MD/Sonic.md")
        with (
            override_settings(LIBRARY=SMALL_GUARD),
            mock.patch("apps.roms.scanner._try_scan_lock", return_value=False),
            mock.patch("apps.roms.scanner._release_scan_lock") as release,
        ):
            self.assertIsNone(run_library_scan(library=self.library))
        self.assertEqual(LibraryScan.objects.count(), 0)
        release.assert_not_called()

    def assert_lock_free_from_another_session(self):
        db = connection.settings_dict
        other = psycopg2.connect(
            dbname=db["NAME"], user=db["USER"], password=db["PASSWORD"], host=db["HOST"], port=db["PORT"] or None
        )
        try:
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [scanner.SCAN_LOCK_KEY])
                free = cursor.fetchone()[0]
                cursor.execute("SELECT pg_advisory_unlock(%s)", [scanner.SCAN_LOCK_KEY])
        finally:
            other.close()
        self.assertTrue(free)

    def test_lock_is_released_after_a_scan(self):
        self.touch("ROMS/MD/Sonic.md")
        scan, _ = self.run_scan()
        self.assertEqual(scan.state, "ok")
        self.assert_lock_free_from_another_session()

    def test_lock_is_released_after_a_failed_scan(self):
        with (
            override_settings(LIBRARY=SMALL_GUARD),
            mock.patch.object(scanner, "scan_library", side_effect=RuntimeError("boom")),
        ):
            run_library_scan(library=self.library)
        self.assert_lock_free_from_another_session()

    def test_enqueue_failure_does_not_fail_the_scan(self):
        self.touch("ROMS/MD/Sonic.md")
        with (
            override_settings(LIBRARY=SMALL_GUARD),
            mock.patch("birdroms.tasks.scrape_rom_cover", side_effect=RuntimeError("broker down")),
            self.assertLogs("apps.roms.scanner", "ERROR"),
        ):
            scan = run_library_scan(library=self.library)
        scan.refresh_from_db()
        self.assertEqual(scan.state, "ok")

    def test_enqueues_covers_only_for_added_roms_without_cover_art(self):
        self.touch("ROMS/SFC/With Cover.smc")
        self.touch("ROMS/SFC/Imgs/With Cover.png")
        self.touch("ROMS/SFC/No Cover.smc")
        scan, scrape = self.run_scan()
        self.assertEqual(scan.state, "ok")
        scrape.assert_called_once_with(ROM.objects.get(file="ROMS/SFC/No Cover.smc").pk)


class ScanLibraryCommandTests(ScannerTestCase):
    def call(self):
        out = io.StringIO()
        with (
            override_settings(LIBRARY=SMALL_GUARD),
            mock.patch("apps.roms.management.commands.scan_library.get_library", return_value=self.library),
            mock.patch("birdroms.tasks.scrape_rom_cover"),
        ):
            call_command("scan_library", stdout=out)
        return out.getvalue()

    def test_prints_counters_and_unknown_folders(self):
        self.touch("ROMS/MD/Sonic.md")
        self.touch("ROMS/NOPE/thing.bin")
        output = self.call()
        self.assertIn("added: 1", output)
        self.assertIn("NOPE", output)

    def test_exits_nonzero_when_aborted(self):
        with self.assertRaises(CommandError) as ctx:
            self.call()
        self.assertEqual(ctx.exception.returncode, 1)

    def test_reports_a_busy_lock(self):
        with (
            mock.patch("apps.roms.scanner._try_scan_lock", return_value=False),
            mock.patch("apps.roms.management.commands.scan_library.get_library", return_value=self.library),
            self.assertRaises(CommandError) as ctx,
        ):
            call_command("scan_library", stdout=io.StringIO())
        self.assertIn("already running", str(ctx.exception))


class ScanCrontabTests(SimpleTestCase):
    def test_defaults_to_every_fifteen_minutes(self):
        validator = parse_scan_crontab({})
        self.assertTrue(validator(datetime.datetime(2026, 1, 5, 13, 15)))
        self.assertFalse(validator(datetime.datetime(2026, 1, 5, 13, 10)))

    def test_env_overrides_the_schedule(self):
        validator = parse_scan_crontab({"LIBRARY_SCAN_CRONTAB": "0 4 * * *"})
        self.assertTrue(validator(datetime.datetime(2026, 1, 5, 4, 0)))
        self.assertFalse(validator(datetime.datetime(2026, 1, 5, 4, 15)))

    def test_malformed_expression_fails_fast(self):
        with self.assertRaises(ImproperlyConfigured):
            parse_scan_crontab({"LIBRARY_SCAN_CRONTAB": "often"})
