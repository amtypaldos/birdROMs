from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from birdroms.auth_config import (
    parse_cache_settings,
    parse_device_token_idle_days,
    parse_invite_ttl_days,
    parse_oidc_settings,
    parse_session_age,
)


class InviteTtlTests(SimpleTestCase):
    def test_defaults_to_seven_days(self):
        self.assertEqual(parse_invite_ttl_days({}), 7)

    def test_reads_env(self):
        self.assertEqual(parse_invite_ttl_days({"INVITE_TTL_DAYS": "30"}), 30)

    def test_rejects_zero_negative_and_garbage(self):
        for raw in ("0", "-1", "soon"):
            with self.subTest(raw=raw), self.assertRaises(ImproperlyConfigured):
                parse_invite_ttl_days({"INVITE_TTL_DAYS": raw})


class SessionAgeTests(SimpleTestCase):
    def test_defaults_to_fourteen_days_in_seconds(self):
        self.assertEqual(parse_session_age({}), 14 * 24 * 3600)

    def test_reads_env_seconds(self):
        self.assertEqual(parse_session_age({"SESSION_COOKIE_AGE": "3600"}), 3600)

    def test_rejects_non_positive(self):
        for raw in ("0", "-5", "x"):
            with self.subTest(raw=raw), self.assertRaises(ImproperlyConfigured):
                parse_session_age({"SESSION_COOKIE_AGE": raw})


class DeviceIdleTests(SimpleTestCase):
    def test_default_is_a_year(self):
        self.assertEqual(parse_device_token_idle_days({}), 365)

    def test_zero_means_never(self):
        self.assertEqual(parse_device_token_idle_days({"DEVICE_TOKEN_IDLE_DAYS": "0"}), 0)

    def test_rejects_negative_and_garbage(self):
        for raw in ("-1", "abc"):
            with self.subTest(raw=raw), self.assertRaises(ImproperlyConfigured):
                parse_device_token_idle_days({"DEVICE_TOKEN_IDLE_DAYS": raw})


class CacheSettingsTests(SimpleTestCase):
    def test_locmem_without_redis_url(self):
        caches = parse_cache_settings({})
        self.assertEqual(caches["default"]["BACKEND"], "django.core.cache.backends.locmem.LocMemCache")

    def test_redis_cache_when_redis_url_set(self):
        caches = parse_cache_settings({"REDIS_URL": "redis://redis:6379/0"})
        self.assertEqual(caches["default"]["BACKEND"], "django.core.cache.backends.redis.RedisCache")
        self.assertEqual(caches["default"]["LOCATION"], "redis://redis:6379/0")


class OidcAllowListParsingTests(SimpleTestCase):
    base = {"OIDC_ISSUER": "https://id.example.com"}

    def test_empty_by_default(self):
        config = parse_oidc_settings(self.base, set())
        self.assertEqual(config["ALLOWED_GROUPS"], [])
        self.assertEqual(config["ALLOWED_EMAIL_DOMAINS"], [])

    def test_comma_separated_lists_are_trimmed_and_domains_normalised(self):
        config = parse_oidc_settings(
            {**self.base, "OIDC_ALLOWED_GROUPS": " friends , family ,", "OIDC_ALLOWED_EMAIL_DOMAINS": "@Example.com, b.org"},
            set(),
        )
        self.assertEqual(config["ALLOWED_GROUPS"], ["friends", "family"])
        self.assertEqual(config["ALLOWED_EMAIL_DOMAINS"], ["example.com", "b.org"])
