import datetime

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from huey import MemoryHuey, RedisHuey

from birdroms.deploy_config import check_secret_key, parse_csv, parse_debug, parse_proxy_settings
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
