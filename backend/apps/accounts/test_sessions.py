import importlib
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.models import DeviceToken
from apps.accounts.services import registration_enabled, set_role


class CookieSessionTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="carol", password="correct-horse")
        set_role(self.user, "readonly")

    def csrf_client(self):
        """A client that enforces CSRF like a browser and carries the CSRF cookie."""
        client = APIClient(enforce_csrf_checks=True)
        response = client.get(reverse("auth-csrf"))
        self.assertEqual(response.status_code, 200)
        client.token = client.cookies["csrftoken"].value
        return client

    def login(self, client, password="correct-horse"):
        return client.post(
            reverse("login"),
            {"username": "carol", "password": password},
            format="json",
            HTTP_X_CSRFTOKEN=client.token,
        )

    def test_csrf_endpoint_sets_a_script_readable_cookie(self):
        response = self.client.get(reverse("auth-csrf"))
        morsel = response.cookies["csrftoken"]
        self.assertFalse(morsel["httponly"])
        self.assertEqual(morsel["samesite"], "Lax")

    def test_login_starts_an_httponly_session_and_returns_no_token(self):
        client = self.csrf_client()
        response = self.login(client)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["username"], "carol")
        self.assertNotIn("token", response.data)
        session = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(session["httponly"])
        self.assertEqual(session["samesite"], "Lax")
        self.assertEqual(client.get(reverse("me")).data["username"], "carol")

    def test_login_with_wrong_password_is_refused_without_a_session(self):
        client = self.csrf_client()
        response = self.login(client, password="nope")

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertIn(client.get(reverse("me")).status_code, (401, 403))

    def test_login_requires_a_csrf_token(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.post(reverse("login"), {"username": "carol", "password": "correct-horse"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_inactive_user_cannot_log_in(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self.login(self.csrf_client()).status_code, 400)

    def test_unsafe_requests_with_a_session_need_the_csrf_header(self):
        client = self.csrf_client()
        self.login(client)
        # A login rotates the CSRF token; the browser would now hold the new cookie.
        client.token = client.cookies["csrftoken"].value

        without = client.post("/api/devices/pair/approve", {"code": "ABCDEF"}, format="json")
        self.assertEqual(without.status_code, 403)

        with_header = client.post(
            "/api/devices/pair/approve", {"code": "ABCDEF"}, format="json", HTTP_X_CSRFTOKEN=client.token
        )
        self.assertEqual(with_header.status_code, 404)  # CSRF passed; the code is just unknown

    def test_logout_ends_the_session(self):
        client = self.csrf_client()
        self.login(client)
        client.token = client.cookies["csrftoken"].value

        response = client.post(reverse("logout"), HTTP_X_CSRFTOKEN=client.token)

        self.assertEqual(response.status_code, 204)
        self.assertIn(client.get(reverse("me")).status_code, (401, 403))

    def test_logout_requires_a_csrf_token(self):
        client = self.csrf_client()
        self.login(client)
        self.assertEqual(client.post(reverse("logout")).status_code, 403)
        self.assertEqual(client.get(reverse("me")).status_code, 200)

    def test_logout_without_a_session_is_harmless(self):
        client = self.csrf_client()
        self.assertEqual(client.post(reverse("logout"), HTTP_X_CSRFTOKEN=client.token).status_code, 204)

    def test_old_drf_tokens_are_not_accepted(self):
        response = self.client.get(reverse("me"), HTTP_AUTHORIZATION="Token 0123456789abcdef0123456789abcdef01234567")
        self.assertEqual(response.status_code, 401)

    def test_session_settings(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 14 * 24 * 3600)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)  # renewed on activity
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")

    def test_changing_the_password_invalidates_existing_sessions(self):
        client = self.csrf_client()
        self.login(client)
        self.user.set_password("another-pass-99")
        self.user.save()
        self.assertIn(client.get(reverse("me")).status_code, (401, 403))

    def test_register_is_still_closed_unless_opened(self):
        self.assertFalse(registration_enabled())
        client = self.csrf_client()
        response = client.post(
            "/api/auth/register/",
            {"username": "newbie", "password": "s3cure-pass-xyz"},
            format="json",
            HTTP_X_CSRFTOKEN=client.token,
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(User.objects.filter(username="newbie").exists())

    @override_settings(ALLOW_REGISTRATION=True)
    def test_register_when_open_signs_in_with_a_session_and_no_token(self):
        client = self.csrf_client()
        response = client.post(
            "/api/auth/register/",
            {"username": "newbie", "password": "s3cure-pass-xyz"},
            format="json",
            HTTP_X_CSRFTOKEN=client.token,
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("token", response.data)
        self.assertTrue(response.cookies[settings.SESSION_COOKIE_NAME]["httponly"])
        self.assertEqual(client.get(reverse("me")).data["username"], "newbie")

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=False)
    def test_login_404_when_local_login_is_off(self):
        self.assertEqual(self.login(self.csrf_client()).status_code, 404)


class LoginIPThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_user(username="carol", password="correct-horse")

    def attempt(self, username, **extra):
        return self.client.post(reverse("login"), {"username": username, "password": "wrong"}, format="json", **extra)

    def test_one_address_is_limited_across_many_usernames(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"login_ip": "3/min"}):
            codes = [self.attempt(f"user{i}").status_code for i in range(4)]
        self.assertEqual(codes, [400, 400, 400, 429])

    def test_other_addresses_are_unaffected(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"login_ip": "1/min"}):
            self.assertEqual(self.attempt("a", REMOTE_ADDR="198.51.100.1").status_code, 400)
            self.assertEqual(self.attempt("b", REMOTE_ADDR="198.51.100.1").status_code, 429)
            self.assertEqual(self.attempt("c", REMOTE_ADDR="198.51.100.2").status_code, 400)


class AdminLoginThrottleTests(TestCase):
    url = "/admin/login/"

    def setUp(self):
        cache.clear()

    def post(self, username="boss"):
        return self.client.post(self.url, {"username": username, "password": "wrong", "next": "/admin/"})

    def test_admin_login_post_returns_429_when_the_throttle_refuses(self):
        with mock.patch("apps.accounts.throttles.AdminLoginThrottle.allow_request", return_value=False):
            response = self.post()
        self.assertEqual(response.status_code, 429)

    def test_repeated_posts_for_one_username_are_limited(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"admin_login": "2/min"}):
            codes = [self.post().status_code for _ in range(3)]
            other = self.post("someone-else").status_code
        self.assertEqual(codes, [200, 200, 429])  # the form re-renders with an error until limited
        self.assertEqual(other, 200)

    def test_username_case_does_not_bypass_the_throttle(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"admin_login": "1/min"}):
            self.assertEqual(self.post("Boss").status_code, 200)
            self.assertEqual(self.post("BOSS").status_code, 429)

    def test_viewing_the_login_form_is_not_throttled(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"admin_login": "1/min"}):
            codes = [self.client.get(self.url).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 200])


class DeviceTokenIdleTests(APITestCase):
    url = reverse("me")

    def setUp(self):
        self.user = User.objects.create_user("owner", password="s3cure-pass-xyz")
        set_role(self.user, "readonly")
        self.token, self.raw = DeviceToken.mint(self.user)

    def age(self, days, field="last_used_at"):
        when = timezone.now() - timedelta(days=days)
        DeviceToken.objects.filter(pk=self.token.pk).update(**{field: when})
        return when

    def get(self):
        return self.client.get(self.url, HTTP_AUTHORIZATION=f"Device {self.raw}")

    @override_settings(DEVICE_TOKEN_IDLE_DAYS=30)
    def test_a_recently_used_token_works_and_is_bumped(self):
        self.age(29)
        self.assertEqual(self.get().status_code, 200)
        self.token.refresh_from_db()
        self.assertLess(timezone.now() - self.token.last_used_at, timedelta(minutes=1))

    @override_settings(DEVICE_TOKEN_IDLE_DAYS=30)
    def test_an_idle_token_is_rejected_and_last_used_at_is_not_bumped(self):
        stale = self.age(31)
        response = self.get()
        self.assertEqual(response.status_code, 401)
        self.token.refresh_from_db()
        self.assertEqual(self.token.last_used_at, stale)
        # Still rejected on the next try: rejection did not count as use.
        self.assertEqual(self.get().status_code, 401)
        self.token.refresh_from_db()
        self.assertEqual(self.token.last_used_at, stale)

    @override_settings(DEVICE_TOKEN_IDLE_DAYS=30)
    def test_a_never_used_token_idles_from_its_creation_date(self):
        DeviceToken.objects.filter(pk=self.token.pk).update(last_used_at=None)
        self.age(31, field="created_at")
        self.assertEqual(self.get().status_code, 401)
        self.token.refresh_from_db()
        self.assertIsNone(self.token.last_used_at)

    @override_settings(DEVICE_TOKEN_IDLE_DAYS=30)
    def test_a_never_used_new_token_works(self):
        DeviceToken.objects.filter(pk=self.token.pk).update(last_used_at=None)
        self.assertEqual(self.get().status_code, 200)

    @override_settings(DEVICE_TOKEN_IDLE_DAYS=0)
    def test_zero_means_a_token_never_idles_out(self):
        self.age(10_000)
        self.assertEqual(self.get().status_code, 200)

    def test_the_default_window_is_a_year(self):
        self.assertEqual(settings.DEVICE_TOKEN_IDLE_DAYS, 365)
        self.age(364)
        self.assertEqual(self.get().status_code, 200)
        self.age(366)
        self.assertEqual(self.get().status_code, 401)

    @override_settings(DEVICE_TOKEN_IDLE_DAYS=30)
    def test_idle_token_cannot_write_either(self):
        self.age(31)
        response = self.client.post("/api/roms/", {"title": "x"}, format="json", HTTP_AUTHORIZATION=f"Device {self.raw}")
        self.assertEqual(response.status_code, 401)  # expiry is judged before the read-only rule


class DeleteWebApiTokensMigrationTests(TestCase):
    """The data migration drops legacy DRF tokens (the `authtoken` app is no longer installed)."""

    def run_migration(self):
        module = importlib.import_module("apps.accounts.migrations.0005_delete_web_api_tokens")
        module.delete_api_tokens(None, mock.Mock(connection=connection))

    def test_clears_the_legacy_token_table_when_it_exists(self):
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE authtoken_token (key varchar(40) PRIMARY KEY, user_id integer)")
            cursor.execute("INSERT INTO authtoken_token VALUES ('abc', 1), ('def', 2)")
        self.run_migration()
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM authtoken_token")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_is_a_no_op_when_the_table_never_existed(self):
        self.assertNotIn("authtoken_token", connection.introspection.table_names())
        self.run_migration()

    def test_depends_on_the_invite_migration_which_follows_registration_settings(self):
        migrations = {
            name: importlib.import_module(f"apps.accounts.migrations.{name}")
            for name in ("0004_invite", "0005_delete_web_api_tokens")
        }
        self.assertIn(("accounts", "0003_registration_settings"), migrations["0004_invite"].Migration.dependencies)
        self.assertEqual(migrations["0005_delete_web_api_tokens"].Migration.dependencies, [("accounts", "0004_invite")])
