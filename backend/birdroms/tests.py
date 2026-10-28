import datetime
import os
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from huey import MemoryHuey, RedisHuey

from birdroms.deploy_config import check_secret_key, parse_csv, parse_debug, parse_num_proxies, parse_proxy_settings
from birdroms.huey_config import build_huey, parse_sweep_crontab


class SecretKeyCheckTests(SimpleTestCase):
    def test_placeholder_keys_are_rejected_in_production(self):
        for key in ("", "  ", "unsafe-dev-secret-key", "change-me"):
            with self.subTest(key=key), self.assertRaises(ImproperlyConfigured):
                check_secret_key(key, debug=False)

    def test_placeholder_keys_are_allowed_under_debug(self):
        check_secret_key("unsafe-dev-secret-key", debug=True)

    def test_real_key_is_accepted_in_production(self):
        check_secret_key("a-long-random-value-from-secrets-token-urlsafe", debug=False)


class ParseDebugTests(SimpleTestCase):
    def test_debug_is_off_unless_explicitly_enabled(self):
        self.assertFalse(parse_debug({}))
        self.assertFalse(parse_debug({"DJANGO_DEBUG": ""}))
        self.assertFalse(parse_debug({"DJANGO_DEBUG": "False"}))
        self.assertFalse(parse_debug({"DJANGO_DEBUG": "yes please"}))

    def test_debug_can_be_enabled_for_development(self):
        self.assertTrue(parse_debug({"DJANGO_DEBUG": "True"}))
        self.assertTrue(parse_debug({"DJANGO_DEBUG": " true "}))


    def test_only_the_literal_true_enables_debug(self):
        for value in ("1", "yes", "on"):
            with self.subTest(value=value):
                self.assertFalse(parse_debug({"DJANGO_DEBUG": value}))

    def test_secret_key_error_names_the_exact_debug_value(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "exactly 'True'"):
            check_secret_key("change-me", debug=False)


class ParseNumProxiesTests(SimpleTestCase):
    def test_defaults_to_one_proxy(self):
        self.assertEqual(parse_num_proxies({}), 1)
        self.assertEqual(parse_num_proxies({"NUM_PROXIES": "  "}), 1)

    def test_reads_the_configured_count(self):
        self.assertEqual(parse_num_proxies({"NUM_PROXIES": "2"}), 2)
        self.assertEqual(parse_num_proxies({"NUM_PROXIES": "0"}), 0)

    def test_rejects_invalid_values(self):
        for value in ("-1", "two", "1.5"):
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                parse_num_proxies({"NUM_PROXIES": value})

    def test_settings_wire_it_into_drf(self):
        from django.conf import settings

        self.assertEqual(settings.REST_FRAMEWORK["NUM_PROXIES"], parse_num_proxies(os.environ))


class ParseCsvTests(SimpleTestCase):
    def test_splits_and_strips_ignoring_blanks(self):
        env = {"DJANGO_ALLOWED_HOSTS": " roms.example.com, ,backend,"}
        self.assertEqual(parse_csv(env, "DJANGO_ALLOWED_HOSTS"), ["roms.example.com", "backend"])

    def test_missing_is_empty(self):
        self.assertEqual(parse_csv({}, "DJANGO_ALLOWED_HOSTS"), [])


class ProxySettingsTests(SimpleTestCase):
    def test_defaults_are_plain_http(self):
        settings = parse_proxy_settings({})
        self.assertEqual(settings["CSRF_TRUSTED_ORIGINS"], [])
        self.assertIsNone(settings["SECURE_PROXY_SSL_HEADER"])
        self.assertFalse(settings["SESSION_COOKIE_SECURE"])
        self.assertFalse(settings["CSRF_COOKIE_SECURE"])

    def test_behind_https_proxy_trusts_forwarded_proto_and_secures_cookies(self):
        settings = parse_proxy_settings(
            {
                "DJANGO_BEHIND_HTTPS_PROXY": "True",
                "DJANGO_CSRF_TRUSTED_ORIGINS": "https://roms.example.com,https://alt.example.com",
            }
        )
        self.assertEqual(settings["SECURE_PROXY_SSL_HEADER"], ("HTTP_X_FORWARDED_PROTO", "https"))
        self.assertTrue(settings["SESSION_COOKIE_SECURE"])
        self.assertTrue(settings["CSRF_COOKIE_SECURE"])
        self.assertEqual(
            settings["CSRF_TRUSTED_ORIGINS"], ["https://roms.example.com", "https://alt.example.com"]
        )

    def test_invalid_bool_fails_fast(self):
        with self.assertRaises(ImproperlyConfigured):
            parse_proxy_settings({"DJANGO_BEHIND_HTTPS_PROXY": "maybe"})


class PublicUrlBehindProxyTests(SimpleTestCase):
    """The public https URL must be rebuilt from the proxy's headers (e.g. for absolute links)."""

    def _absolute_root(self, behind_proxy, **headers):
        from django.test import RequestFactory, override_settings

        proxy = parse_proxy_settings({"DJANGO_BEHIND_HTTPS_PROXY": "True" if behind_proxy else "False"})
        with override_settings(
            ALLOWED_HOSTS=["roms.example.com"], SECURE_PROXY_SSL_HEADER=proxy["SECURE_PROXY_SSL_HEADER"]
        ):
            request = RequestFactory().get("/api/anything/", **headers)
            return request.build_absolute_uri("/")

    def test_forwarded_proto_and_host_give_the_public_https_url(self):
        url = self._absolute_root(True, HTTP_HOST="roms.example.com", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(url, "https://roms.example.com/")

    def test_without_the_proxy_setting_the_scheme_is_http(self):
        url = self._absolute_root(False, HTTP_HOST="roms.example.com", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(url, "http://roms.example.com/")

    def test_host_outside_allowed_hosts_is_rejected(self):
        from django.core.exceptions import DisallowedHost

        with self.assertRaises(DisallowedHost):
            self._absolute_root(True, HTTP_HOST="evil.example.net", HTTP_X_FORWARDED_PROTO="https")


class HueyConfigTests(SimpleTestCase):
    def test_huey_immediate_in_debug(self):
        huey = build_huey({}, debug=True)
        self.assertIsInstance(huey, MemoryHuey)
        self.assertTrue(huey.immediate)

    def test_huey_immediate_when_flag_set_outside_debug(self):
        huey = build_huey({"HUEY_IMMEDIATE": "true", "REDIS_URL": "redis://cache:6379/1"}, debug=False)
        self.assertTrue(huey.immediate)

    def test_redis_backend_selected_when_not_immediate(self):
        env = {"HUEY_IMMEDIATE": "false", "REDIS_URL": "redis://cache.example:6380/2"}
        huey = build_huey(env, debug=False)
        self.assertIsInstance(huey, RedisHuey)
        self.assertFalse(huey.immediate)
        params = huey.storage.pool.connection_kwargs
        self.assertEqual((params["host"], params["port"], params["db"]), ("cache.example", 6380, 2))

    def test_redis_url_defaults_to_localhost(self):
        huey = build_huey({"HUEY_IMMEDIATE": "false"}, debug=False)
        self.assertEqual(huey.storage.pool.connection_kwargs["host"], "localhost")

    def test_invalid_immediate_flag_fails_fast(self):
        with self.assertRaises(ImproperlyConfigured):
            build_huey({"HUEY_IMMEDIATE": "maybe"}, debug=False)


class SweepCrontabTests(SimpleTestCase):
    def test_defaults_to_top_of_every_hour(self):
        validator = parse_sweep_crontab({})
        self.assertTrue(validator(datetime.datetime(2026, 1, 5, 13, 0)))
        self.assertFalse(validator(datetime.datetime(2026, 1, 5, 13, 30)))

    def test_env_overrides_the_schedule(self):
        validator = parse_sweep_crontab({"COVER_ART_SWEEP_CRONTAB": "*/15 3 * * *"})
        self.assertTrue(validator(datetime.datetime(2026, 1, 5, 3, 45)))
        self.assertFalse(validator(datetime.datetime(2026, 1, 5, 4, 45)))

    def test_malformed_expression_fails_fast(self):
        with self.assertRaises(ImproperlyConfigured):
            parse_sweep_crontab({"COVER_ART_SWEEP_CRONTAB": "hourly"})


class HueyWrapperTests(SimpleTestCase):
    def test_wrapper_exposes_the_configured_instance(self):
        from django.conf import settings

        from birdroms import tasks

        self.assertIs(tasks.huey, settings.HUEY)
        self.assertTrue(tasks.huey.immediate)  # the test run never needs a live Redis

    def test_task_decorator_runs_inline_in_immediate_mode(self):
        from birdroms.tasks import task

        @task()
        def add(a, b):
            return a + b

        self.assertEqual(add(2, 3)(), 5)

    def test_seam_exposes_db_task_decorators(self):
        from huey.contrib import djhuey

        from birdroms import tasks

        self.assertIs(tasks.db_task, djhuey.db_task)
        self.assertIs(tasks.db_periodic_task, djhuey.db_periodic_task)

    def test_db_task_runs_inline_in_immediate_mode(self):
        from birdroms.tasks import db_task

        @db_task()
        def add_with_db(a, b):
            return a + b

        self.assertEqual(add_with_db(2, 3)(), 5)

    def test_cover_art_tasks_close_stale_connections_on_a_worker(self):
        from birdroms import tasks

        # A real worker is not in immediate mode; simulate that for the wrapped function only.
        for task in (tasks.scrape_rom_cover, tasks.sweep_missing_cover_art):
            with self.subTest(task=task.task_class.__name__):
                with mock.patch.object(type(tasks.huey), "immediate", new_callable=mock.PropertyMock, return_value=False), \
                        mock.patch("huey.contrib.djhuey.close_old_connections") as close:
                    with mock.patch("birdroms.tasks.ROM.objects"), mock.patch("birdroms.tasks.roms_missing_cover_art"):
                        task.func(*([1] if task is tasks.scrape_rom_cover else []))
                self.assertEqual(close.call_count, 2)
