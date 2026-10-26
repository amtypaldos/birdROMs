from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from birdroms.deploy_config import check_secret_key, parse_csv, parse_proxy_settings


class SecretKeyCheckTests(SimpleTestCase):
    def test_placeholder_keys_are_rejected_in_production(self):
        for key in ("", "  ", "unsafe-dev-secret-key", "change-me"):
            with self.subTest(key=key), self.assertRaises(ImproperlyConfigured):
                check_secret_key(key, debug=False)

    def test_placeholder_keys_are_allowed_under_debug(self):
        check_secret_key("unsafe-dev-secret-key", debug=True)

    def test_real_key_is_accepted_in_production(self):
        check_secret_key("a-long-random-value-from-secrets-token-urlsafe", debug=False)


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
