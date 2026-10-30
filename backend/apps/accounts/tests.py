from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.http import HttpResponseRedirect
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import (
    PAIRING_CODE_ALPHABET,
    DeviceToken,
    OIDCIdentity,
    PairingRequest,
    RegistrationSettings,
    hash_device_token,
)
from apps.accounts.services import expire_stale_pairings, registration_enabled, set_role, user_role
from apps.roms.models import ROM, Playlist
from birdroms.auth_config import (
    parse_allow_local_login,
    parse_allow_registration,
    parse_auth_methods,
    parse_oidc_settings,
)
from birdroms.tasks import sweep_expired_pairings


@override_settings(AUTH_METHODS={"local"}, ALLOW_LOCAL_LOGIN=False, ALLOW_REGISTRATION=True)
class RegisterTests(APITestCase):
    url = reverse("register")

    def setUp(self):
        cache.clear()  # Throttle counters live in the cache.

    def test_register_creates_readonly_user_and_signs_in_without_a_token(self):
        response = self.client.post(
            self.url,
            {"username": "alice", "email": "alice@example.com", "password": "s3cure-pass"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username="alice")
        self.assertTrue(user.groups.filter(name="readonly").exists())
        self.assertNotIn("token", response.data)
        self.assertEqual(response.data["user"]["username"], "alice")
        self.assertNotIn("password", response.data["user"])
        session = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(session["httponly"])
        self.assertEqual(self.client.get(reverse("me")).data["username"], "alice")  # signed in by cookie

    def test_register_requires_a_csrf_token(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.post(
            self.url, {"username": "alice", "email": "", "password": "s3cure-pass-xyz"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_register_rejects_short_password(self):
        response = self.client.post(
            self.url,
            {"username": "bob", "email": "bob@example.com", "password": "short"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)
        self.assertFalse(User.objects.filter(username="bob").exists())

    def test_register_enforces_django_password_validators(self):
        for password in ("password", "12345678", "alice123"):
            with self.subTest(password=password):
                response = self.client.post(
                    self.url, {"username": "alice", "email": "a@example.com", "password": password}, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, password)
                self.assertIn("password", response.data)
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_register_is_rate_limited_per_client(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"register": "2/min"}):
            codes = [
                self.client.post(
                    self.url, {"username": f"user{i}", "email": "", "password": "s3cure-pass-xyz"}, format="json"
                ).status_code
                for i in range(3)
            ]
        self.assertEqual(codes, [201, 201, 429])

    def test_register_throttle_ignores_client_supplied_forwarded_for_entries(self):
        # One trusted proxy: only the last X-Forwarded-For entry (appended by it) is the client.
        drf = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
        with override_settings(REST_FRAMEWORK=drf), mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"register": "2/min"}):
            codes = [
                self.client.post(
                    self.url,
                    {"username": f"user{i}", "email": "", "password": "s3cure-pass-xyz"},
                    format="json",
                    HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.7",
                ).status_code
                for i in range(3)
            ]
        self.assertEqual(codes, [201, 201, 429])


class LoginTests(APITestCase):
    url = reverse("login")

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="carol", password="correct-horse")

    def test_login_with_valid_credentials_starts_a_session(self):
        response = self.client.post(self.url, {"username": "carol", "password": "correct-horse"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("token", response.data)
        self.assertEqual(response.data["user"]["username"], "carol")
        self.assertEqual(self.client.get(reverse("me")).data["username"], "carol")

    def test_login_with_invalid_credentials_returns_400(self):
        response = self.client.post(self.url, {"username": "carol", "password": "wrong-password"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("token", response.data)


class LoginThrottleTests(APITestCase):
    url = reverse("login")

    def setUp(self):
        cache.clear()
        User.objects.create_user(username="carol", password="correct-horse")

    def attempt(self, username="carol", password="wrong", **extra):
        return self.client.post(self.url, {"username": username, "password": password}, format="json", **extra)

    def test_repeated_failures_for_one_username_are_throttled(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"login": "3/min"}):
            codes = [self.attempt().status_code for _ in range(4)]
            self.assertEqual(codes, [400, 400, 400, 429])
            # Even the right password is refused while throttled.
            self.assertEqual(self.attempt(password="correct-horse").status_code, 429)

    def test_throttle_cannot_be_dodged_by_spoofing_the_client_address(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"login": "2/min"}):
            codes = [self.attempt(HTTP_X_FORWARDED_FOR=f"10.0.0.{i}").status_code for i in range(3)]
        self.assertEqual(codes, [400, 400, 429])

    def test_other_usernames_are_unaffected(self):
        User.objects.create_user(username="dave", password="another-pass")
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"login": "1/min"}):
            self.assertEqual(self.attempt().status_code, 400)
            self.assertEqual(self.attempt().status_code, 429)
            self.assertEqual(self.attempt("dave", "another-pass").status_code, 200)

    def test_username_case_does_not_bypass_the_throttle(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"login": "1/min"}):
            self.assertEqual(self.attempt("carol").status_code, 400)
            self.assertEqual(self.attempt("CAROL").status_code, 429)


OIDC_TEST_CONFIG = parse_oidc_settings(
    {
        "OIDC_ISSUER": "https://id.example.com",
        "OIDC_CLIENT_ID": "birdroms",
        "OIDC_CLIENT_SECRET": "test-secret",
        "OIDC_REDIRECT_URI": "http://testserver/api/auth/oidc/callback/",
        "OIDC_ADMIN_GROUP": "birdroms-admins",
        "OIDC_LOGIN_REDIRECT_URL": "http://spa.example/",
        "OIDC_PROVIDER_NAME": "Pocket ID",
    },
    {"oidc"},
)


class AuthSettingsParsingTests(SimpleTestCase):
    def test_auth_methods_default_to_local_and_ignore_order_and_case(self):
        self.assertEqual(parse_auth_methods({}), {"local"})
        self.assertEqual(parse_auth_methods({"AUTH_METHODS": " OIDC, local "}), {"local", "oidc"})

    def test_unknown_auth_method_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            parse_auth_methods({"AUTH_METHODS": "local,saml"})

    def test_allow_local_login_defaults_to_debug(self):
        self.assertTrue(parse_allow_local_login({}, debug=True))
        self.assertFalse(parse_allow_local_login({}, debug=False))
        self.assertTrue(parse_allow_local_login({"ALLOW_LOCAL_LOGIN": "true"}, debug=False))
        self.assertFalse(parse_allow_local_login({"ALLOW_LOCAL_LOGIN": "False"}, debug=True))
        with self.assertRaises(ImproperlyConfigured):
            parse_allow_local_login({"ALLOW_LOCAL_LOGIN": "maybe"}, debug=True)

    def test_allow_registration_parsing(self):
        self.assertIsNone(parse_allow_registration({}))
        self.assertIsNone(parse_allow_registration({"ALLOW_REGISTRATION": "  "}))
        self.assertIs(parse_allow_registration({"ALLOW_REGISTRATION": "yes"}), True)
        self.assertIs(parse_allow_registration({"ALLOW_REGISTRATION": "On"}), True)
        self.assertIs(parse_allow_registration({"ALLOW_REGISTRATION": "no"}), False)
        self.assertIs(parse_allow_registration({"ALLOW_REGISTRATION": "0"}), False)
        with self.assertRaises(ImproperlyConfigured):
            parse_allow_registration({"ALLOW_REGISTRATION": "maybe"})

    def test_oidc_requires_provider_settings_when_enabled(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "OIDC_CLIENT_SECRET"):
            parse_oidc_settings({"OIDC_ISSUER": "https://id", "OIDC_CLIENT_ID": "x", "OIDC_REDIRECT_URI": "y"}, {"oidc"})
        # Not enabled: missing values are fine.
        parse_oidc_settings({}, {"local"})

    def test_discovery_url_derives_from_issuer(self):
        self.assertEqual(OIDC_TEST_CONFIG["DISCOVERY_URL"], "https://id.example.com/.well-known/openid-configuration")
        self.assertEqual(OIDC_TEST_CONFIG["SCOPES"], "openid email profile groups")


class AuthConfigTests(APITestCase):
    url = reverse("auth-config")

    @override_settings(AUTH_METHODS={"local"}, ALLOW_LOCAL_LOGIN=False)
    def test_local_only(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"methods": ["local"], "registration": False, "invites": True})

    @override_settings(AUTH_METHODS={"local"}, ALLOW_LOCAL_LOGIN=False, ALLOW_REGISTRATION=True)
    def test_registration_true_when_local_login_and_registration_open(self):
        response = self.client.get(self.url)
        self.assertEqual(response.data, {"methods": ["local"], "registration": True, "invites": True})

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=False, ALLOW_REGISTRATION=True, OIDC=OIDC_TEST_CONFIG)
    def test_registration_false_when_local_login_is_off(self):
        response = self.client.get(self.url)
        self.assertEqual(response.data["methods"], ["oidc"])
        self.assertIs(response.data["registration"], False)

    @override_settings(AUTH_METHODS={"local"}, ALLOW_LOCAL_LOGIN=False, ALLOW_REGISTRATION=None)
    def test_registration_follows_admin_checkbox_when_env_unset(self):
        self.assertIs(self.client.get(self.url).data["registration"], False)
        RegistrationSettings.objects.update_or_create(pk=1, defaults={"allow_registration": True})
        self.assertIs(self.client.get(self.url).data["registration"], True)

    @override_settings(AUTH_METHODS={"local"}, ALLOW_LOCAL_LOGIN=True, ALLOW_REGISTRATION=True)
    def test_invites_true_when_local_login_is_on(self):
        self.assertIs(self.client.get(self.url).data["invites"], True)

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=False, ALLOW_REGISTRATION=True, OIDC=OIDC_TEST_CONFIG)
    def test_invites_false_when_local_login_is_off(self):
        self.assertIs(self.client.get(self.url).data["invites"], False)

    @override_settings(AUTH_METHODS={"local"}, ALLOW_LOCAL_LOGIN=True)
    def test_invites_do_not_depend_on_self_registration(self):
        for allow in (True, False):
            with self.subTest(allow_registration=allow), override_settings(ALLOW_REGISTRATION=allow):
                data = self.client.get(self.url).data
                self.assertIs(data["registration"], allow)
                self.assertIs(data["invites"], True)

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=False, OIDC=OIDC_TEST_CONFIG)
    def test_oidc_only(self):
        response = self.client.get(self.url)
        self.assertEqual(response.data["methods"], ["oidc"])
        self.assertEqual(response.data["oidc"], {"provider_name": "Pocket ID", "login_url": "/api/auth/oidc/login/"})

    @override_settings(AUTH_METHODS={"oidc", "local"}, ALLOW_LOCAL_LOGIN=False, OIDC=OIDC_TEST_CONFIG)
    def test_both_enabled(self):
        self.assertEqual(self.client.get(self.url).data["methods"], ["local", "oidc"])

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=True, OIDC=OIDC_TEST_CONFIG)
    def test_allow_local_login_adds_local(self):
        self.assertEqual(self.client.get(self.url).data["methods"], ["local", "oidc"])

    def test_config_does_not_leak_secrets(self):
        with override_settings(AUTH_METHODS={"oidc"}, OIDC=OIDC_TEST_CONFIG):
            body = self.client.get(self.url).content.decode()
        self.assertNotIn("test-secret", body)
        self.assertNotIn("birdroms-admins", body)


class LocalLoginGatingTests(APITestCase):
    def setUp(self):
        User.objects.create_user(username="dave", password="correct-horse")

    def login(self):
        return self.client.post(reverse("login"), {"username": "dave", "password": "correct-horse"}, format="json")

    def register(self):
        return self.client.post(
            reverse("register"), {"username": "erin", "email": "e@example.com", "password": "s3cure-pass"}, format="json"
        )

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=False, ALLOW_REGISTRATION=True, OIDC=OIDC_TEST_CONFIG)
    def test_local_endpoints_404_when_disabled(self):
        self.assertEqual(self.login().status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.register().status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(User.objects.filter(username="erin").exists())

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=True, ALLOW_REGISTRATION=True, OIDC=OIDC_TEST_CONFIG)
    def test_allow_local_login_force_enables_local_endpoints(self):
        self.assertEqual(self.login().status_code, status.HTTP_200_OK)
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)

    @override_settings(AUTH_METHODS={"local"}, ALLOW_LOCAL_LOGIN=False, ALLOW_REGISTRATION=None)
    def test_login_works_and_register_404s_when_registration_closed(self):
        self.assertEqual(self.login().status_code, status.HTTP_200_OK)
        self.assertEqual(self.register().status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(User.objects.filter(username="erin").exists())

    @override_settings(AUTH_METHODS={"local", "oidc"}, ALLOW_LOCAL_LOGIN=False, OIDC=OIDC_TEST_CONFIG)
    def test_local_endpoints_work_when_both_enabled(self):
        self.assertEqual(self.login().status_code, status.HTTP_200_OK)


@override_settings(AUTH_METHODS={"local"}, ALLOW_LOCAL_LOGIN=False)
class RegistrationSettingTests(APITestCase):
    """Env `ALLOW_REGISTRATION` (when set) beats the Django-admin singleton; unset falls back to it."""

    def register(self):
        return self.client.post(
            reverse("register"), {"username": "gina", "email": "g@example.com", "password": "s3cure-pass"}, format="json"
        )

    def set_admin(self, value):
        RegistrationSettings.objects.update_or_create(pk=1, defaults={"allow_registration": value})

    def setUp(self):
        cache.clear()

    @override_settings(ALLOW_REGISTRATION=None)
    def test_unset_env_and_no_admin_row_is_closed(self):
        self.assertFalse(RegistrationSettings.objects.exists())
        self.assertFalse(registration_enabled())
        self.assertEqual(self.register().status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(User.objects.filter(username="gina").exists())

    @override_settings(ALLOW_REGISTRATION=None)
    def test_unset_env_and_checkbox_off_is_closed(self):
        self.set_admin(False)
        self.assertEqual(self.register().status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(ALLOW_REGISTRATION=None)
    def test_unset_env_and_checkbox_on_is_open(self):
        self.set_admin(True)
        self.assertTrue(registration_enabled())
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)

    @override_settings(ALLOW_REGISTRATION=True)
    def test_env_true_opens_even_when_checkbox_off(self):
        self.set_admin(False)
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)

    @override_settings(ALLOW_REGISTRATION=False)
    def test_env_false_closes_even_when_checkbox_on(self):
        self.set_admin(True)
        self.assertFalse(registration_enabled())
        self.assertEqual(self.register().status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=False, ALLOW_REGISTRATION=True, OIDC=OIDC_TEST_CONFIG)
    def test_local_login_off_keeps_register_404_even_if_open(self):
        self.assertFalse(registration_enabled())
        self.assertEqual(self.register().status_code, status.HTTP_404_NOT_FOUND)


class RegistrationSettingsModelTests(APITestCase):
    def test_load_creates_the_single_row_closed_by_default(self):
        row = RegistrationSettings.load()
        self.assertEqual(row.pk, 1)
        self.assertFalse(row.allow_registration)
        self.assertEqual(RegistrationSettings.load().pk, 1)
        self.assertEqual(RegistrationSettings.objects.count(), 1)

    def test_save_always_uses_pk_1(self):
        RegistrationSettings(allow_registration=True).save()
        RegistrationSettings(pk=5, allow_registration=False).save()
        self.assertEqual(list(RegistrationSettings.objects.values_list("pk", flat=True)), [1])

    def test_admin_blocks_add_once_row_exists_and_always_blocks_delete(self):
        model_admin = admin.site._registry[RegistrationSettings]
        request = mock.Mock()
        self.assertTrue(model_admin.has_add_permission(request))
        RegistrationSettings.load()
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))

    def test_admin_help_text_mentions_env_override(self):
        help_text = RegistrationSettings._meta.get_field("allow_registration").help_text
        self.assertIn("ALLOW_REGISTRATION", help_text)


class MeTests(APITestCase):
    url = reverse("me")

    def test_requires_authentication(self):
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_returns_user_and_role(self):
        user = User.objects.create_user(username="frank", email="frank@example.com", password="pw-123456")
        set_role(user, "readonly")
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data, {"id": user.id, "username": "frank", "email": "frank@example.com", "role": "readonly"}
        )

    def test_superuser_and_groupless_roles(self):
        admin = User.objects.create_superuser(username="root", password="pw-123456")
        nobody = User.objects.create_user(username="nobody", password="pw-123456")
        self.client.force_authenticate(admin)
        self.assertEqual(self.client.get(self.url).data["role"], "super_admin")
        self.client.force_authenticate(nobody)
        self.assertIsNone(self.client.get(self.url).data["role"])


class RoleResolutionTests(APITestCase):
    def test_user_role_for_each_group(self):
        for role in ("super_admin", "member", "readonly"):
            user = User.objects.create_user(username=f"u-{role}")
            set_role(user, role)
            self.assertEqual(user_role(user), role)
        self.assertIsNone(user_role(User.objects.create_user(username="nobody")))

    def test_most_powerful_group_wins_when_in_several(self):
        user = User.objects.create_user(username="multi")
        for name in ("readonly", "member"):
            user.groups.add(Group.objects.get_or_create(name=name)[0])
        self.assertEqual(user_role(user), "member")
        user.groups.add(Group.objects.get_or_create(name="super_admin")[0])
        self.assertEqual(user_role(user), "super_admin")

    def test_django_superuser_is_super_admin(self):
        self.assertEqual(user_role(User.objects.create_superuser(username="root", password="pw-123456")), "super_admin")

    def test_set_role_leaves_exactly_one_role_group(self):
        user = User.objects.create_user(username="mover")
        for name in ("super_admin", "readonly"):
            user.groups.add(Group.objects.get_or_create(name=name)[0])
        set_role(user, "member")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["member"])
        set_role(user, "readonly")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["readonly"])

    def test_set_role_keeps_unrelated_groups(self):
        user = User.objects.create_user(username="keeper")
        user.groups.add(Group.objects.get_or_create(name="book-club")[0])
        set_role(user, "member")
        self.assertEqual(sorted(user.groups.values_list("name", flat=True)), ["book-club", "member"])

    def test_me_reports_member(self):
        user = User.objects.create_user(username="up")
        set_role(user, "member")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(reverse("me")).data["role"], "member")


def fake_oidc_client(claims, userinfo=None):
    client = mock.Mock()
    client.authorize_redirect.return_value = HttpResponseRedirect("https://id.example.com/authorize?state=abc")
    client.authorize_access_token.return_value = {"access_token": "at", "userinfo": claims}
    client.userinfo.return_value = userinfo or {}
    return client


@override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=False, OIDC=OIDC_TEST_CONFIG)
class OIDCFlowTests(APITestCase):
    callback_url = reverse("oidc-callback")

    def claims(self, **overrides):
        return {
            "iss": "https://id.example.com",
            "sub": "user-123",
            "preferred_username": "grace",
            "email": "grace@example.com",
            "email_verified": True,
            "groups": [],
            **overrides,
        }

    def callback(self, claims, userinfo=None, query="?code=abc&state=xyz"):
        with mock.patch("apps.accounts.views.get_oidc_client", return_value=fake_oidc_client(claims, userinfo)):
            return self.client.get(self.callback_url + query)

    def fragment(self, response):
        """The `oidc_error` fragment of a failed sign-in redirect."""
        self.assertEqual(response.status_code, 302)
        location = response["Location"]
        self.assertTrue(location.startswith("http://spa.example/#"), location)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        return parse_qs(urlparse(location).fragment)

    def signed_in(self, response):
        """A successful sign-in redirects with no token at all; the session cookie is the sign-in."""
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://spa.example/")
        session = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(session["httponly"])
        return self.client.get(reverse("me")).data

    def test_login_redirects_to_provider_with_configured_redirect_uri(self):
        client = fake_oidc_client({})
        with mock.patch("apps.accounts.views.get_oidc_client", return_value=client):
            response = self.client.get(reverse("oidc-login"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("https://id.example.com/authorize"))
        client.authorize_redirect.assert_called_once()
        self.assertEqual(client.authorize_redirect.call_args.args[1], "http://testserver/api/auth/oidc/callback/")

    def test_real_authlib_client_builds_pkce_authorization_redirect(self):
        metadata = {
            "issuer": "https://id.example.com",
            "authorization_endpoint": "https://id.example.com/authorize",
            "token_endpoint": "https://id.example.com/api/oidc/token",
            "jwks_uri": "https://id.example.com/.well-known/jwks.json",
        }
        with mock.patch("authlib.integrations.django_client.DjangoOAuth2App.load_server_metadata", return_value=metadata):
            response = self.client.get(reverse("oidc-login"))

        self.assertEqual(response.status_code, 302)
        location = urlparse(response["Location"])
        query = parse_qs(location.query)
        self.assertEqual(f"{location.scheme}://{location.netloc}{location.path}", "https://id.example.com/authorize")
        self.assertEqual(query["client_id"], ["birdroms"])
        self.assertEqual(query["redirect_uri"], ["http://testserver/api/auth/oidc/callback/"])
        self.assertEqual(query["scope"], ["openid email profile groups"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertIn("state", query)
        self.assertIn("nonce", query)
        self.assertNotIn("test-secret", response["Location"])

    def test_first_login_provisions_readonly_user_and_starts_a_session(self):
        me = self.signed_in(self.callback(self.claims()))

        user = User.objects.get(username="grace")
        self.assertEqual(user.email, "grace@example.com")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user_role(user), "readonly")
        self.assertEqual(OIDCIdentity.objects.get(user=user).subject, "user-123")
        self.assertEqual(me["username"], "grace")

        # The session cookie works against the API.
        self.assertEqual(self.client.get(reverse("me")).data["role"], "readonly")
        self.assertEqual(self.client.get("/api/roms/").status_code, status.HTTP_200_OK)

    def test_admin_group_claim_maps_to_super_admin(self):
        self.signed_in(self.callback(self.claims(groups=["birdroms-admins", "other"])))
        self.assertEqual(user_role(User.objects.get(username="grace")), "super_admin")

    @override_settings(OIDC={**OIDC_TEST_CONFIG, "MEMBER_GROUP": "birdroms-members"})
    def test_upload_group_claim_maps_to_member(self):
        self.signed_in(self.callback(self.claims(groups=["birdroms-members"])))
        user = User.objects.get(username="grace")
        self.assertEqual(user_role(user), "member")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["member"])

    @override_settings(OIDC={**OIDC_TEST_CONFIG, "MEMBER_GROUP": "birdroms-members"})
    def test_admin_group_wins_over_upload_group(self):
        self.signed_in(self.callback(self.claims(groups=["birdroms-members", "birdroms-admins"])))
        self.assertEqual(user_role(User.objects.get(username="grace")), "super_admin")

    @override_settings(OIDC={**OIDC_TEST_CONFIG, "MEMBER_GROUP": "birdroms-members"})
    def test_user_outside_both_groups_stays_readonly(self):
        self.signed_in(self.callback(self.claims(groups=["other"])))
        self.assertEqual(user_role(User.objects.get(username="grace")), "readonly")

    @override_settings(OIDC={**OIDC_TEST_CONFIG, "MEMBER_GROUP": "birdroms-members"})
    def test_upload_role_is_resynced_when_membership_is_removed(self):
        self.callback(self.claims(groups=["birdroms-members"]))
        self.signed_in(self.callback(self.claims(groups=[])))
        self.assertEqual(user_role(User.objects.get(username="grace")), "readonly")

    def test_unset_upload_group_never_assigns_member(self):
        self.assertEqual(OIDC_TEST_CONFIG["MEMBER_GROUP"], "")
        # Even a group literally named like the empty string or "member" grants nothing.
        self.signed_in(self.callback(self.claims(groups=["", "member", "birdroms-members"])))
        self.assertEqual(user_role(User.objects.get(username="grace")), "readonly")

    def test_upload_group_setting_is_parsed_from_env(self):
        config = parse_oidc_settings(
            {"OIDC_ISSUER": "https://id.example.com", "OIDC_CLIENT_ID": "x", "OIDC_CLIENT_SECRET": "y",
             "OIDC_REDIRECT_URI": "http://t/cb", "OIDC_MEMBER_GROUP": " birdroms-members "},
            {"oidc"},
        )
        self.assertEqual(config["MEMBER_GROUP"], "birdroms-members")

    def test_groups_claim_fetched_from_userinfo_when_missing_from_id_token(self):
        claims = self.claims()
        del claims["groups"]
        self.signed_in(self.callback(claims, userinfo={"sub": "user-123", "groups": ["birdroms-admins"]}))
        self.assertEqual(user_role(User.objects.get(username="grace")), "super_admin")

    @override_settings(OIDC={**OIDC_TEST_CONFIG, "GROUPS_CLAIM": "roles"})
    def test_custom_groups_claim(self):
        self.signed_in(self.callback(self.claims(roles="birdroms-admins")))
        self.assertEqual(user_role(User.objects.get(username="grace")), "super_admin")

    def test_returning_user_matches_on_subject_and_role_is_resynced(self):
        self.callback(self.claims(groups=["birdroms-admins"]))
        self.signed_in(self.callback(self.claims(preferred_username="renamed", email="new@example.com")))

        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get()
        self.assertEqual(user.username, "grace")
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(user_role(user), "readonly")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["readonly"])

    def test_username_collision_gets_suffix_and_does_not_hijack_local_account(self):
        local = User.objects.create_user(username="grace", email="grace@example.com", password="pw-123456")

        self.signed_in(self.callback(self.claims()))

        self.assertEqual(User.objects.count(), 2)
        self.assertFalse(hasattr(User.objects.get(pk=local.pk), "oidc_identity"))
        self.assertTrue(User.objects.filter(username="grace-2").exists())

    @override_settings(OIDC={**OIDC_TEST_CONFIG, "LINK_BY_EMAIL": True})
    def test_link_by_verified_email_when_enabled(self):
        local = User.objects.create_user(username="gracelocal", email="Grace@example.com", password="pw-123456")
        self.signed_in(self.callback(self.claims()))
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(OIDCIdentity.objects.get().user, local)

    @override_settings(AUTH_METHODS={"local", "oidc"}, ALLOW_REGISTRATION=True, OIDC={**OIDC_TEST_CONFIG, "LINK_BY_EMAIL": True})
    def test_linking_by_email_evicts_a_pre_registered_squatter(self):
        # Local sign-up does not verify email, so an attacker can pre-register the victim's address
        # and keep the password and a signed-in session. Linking must cut both off.
        attacker = APIClient()
        registered = attacker.post(
            reverse("register"),
            {"username": "squatter", "email": "grace@example.com", "password": "attacker-pass-1"},
            format="json",
        )
        self.assertEqual(registered.status_code, status.HTTP_201_CREATED)
        self.assertEqual(attacker.get(reverse("me")).status_code, status.HTTP_200_OK)

        self.signed_in(self.callback(self.claims()))

        user = User.objects.get(username="squatter")
        self.assertEqual(OIDCIdentity.objects.get().user, user)
        self.assertFalse(user.has_usable_password())
        self.assertIn(attacker.get(reverse("me")).status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        relogin = self.client.post(
            reverse("login"), {"username": "squatter", "password": "attacker-pass-1"}, format="json"
        )
        self.assertEqual(relogin.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(OIDC={**OIDC_TEST_CONFIG, "LINK_BY_EMAIL": True})
    def test_unverified_email_is_never_linked(self):
        User.objects.create_user(username="gracelocal", email="grace@example.com", password="pw-123456")
        self.signed_in(self.callback(self.claims(email_verified=False)))
        self.assertEqual(User.objects.count(), 2)

    def test_inactive_user_is_not_signed_in(self):
        self.callback(self.claims())
        self.client.cookies.clear()
        User.objects.filter(username="grace").update(is_active=False)

        fragment = self.fragment(self.callback(self.claims()))

        self.assertEqual(fragment, {"oidc_error": ["disabled"]})
        self.assertIn(self.client.get(reverse("me")).status_code, (401, 403))

    def test_provider_error_redirects_with_a_fixed_code_never_the_provider_text(self):
        with self.assertLogs("apps.accounts.views", "WARNING"):
            response = self.callback(
                self.claims(), query="?error=access_denied&error_description=%3Cscript%3Ealert(1)%3C/script%3E"
            )
        fragment = self.fragment(response)
        self.assertEqual(fragment, {"oidc_error": ["provider_error"]})
        self.assertNotIn("script", response["Location"])
        self.assertNotIn("access_denied", response["Location"])
        self.assertFalse(User.objects.exists())

    def test_missing_subject_redirects_with_a_fixed_code(self):
        claims = self.claims()
        del claims["sub"]
        self.assertEqual(self.fragment(self.callback(claims)), {"oidc_error": ["no_subject"]})
        self.assertFalse(User.objects.exists())

    def test_every_oidc_error_code_is_a_known_fixed_one(self):
        from apps.accounts.views import OIDC_ERRORS

        self.assertEqual(set(OIDC_ERRORS), {"provider_error", "failed", "no_subject", "disabled", "not_allowed"})

    def test_failed_token_exchange_redirects_with_generic_error(self):
        client = fake_oidc_client({})
        client.authorize_access_token.side_effect = Exception("mismatching_state")
        with mock.patch("apps.accounts.views.get_oidc_client", return_value=client), self.assertLogs(
            "apps.accounts.views", "WARNING"
        ):
            fragment = self.fragment(self.client.get(self.callback_url + "?code=abc&state=bad"))
        self.assertEqual(fragment, {"oidc_error": ["failed"]})
        self.assertFalse(User.objects.exists())

    def allow_list(self, groups=(), domains=()):
        return override_settings(
            OIDC={**OIDC_TEST_CONFIG, "ALLOWED_GROUPS": list(groups), "ALLOWED_EMAIL_DOMAINS": list(domains)}
        )

    def test_no_allow_list_lets_every_provider_user_in(self):
        self.signed_in(self.callback(self.claims(email="anyone@else.org", groups=[])))

    def test_allowed_group_lets_a_member_in(self):
        with self.allow_list(groups=["friends"]):
            self.signed_in(self.callback(self.claims(groups=["other", "friends"])))

    def test_allowed_group_refuses_a_non_member_and_creates_nothing(self):
        with self.allow_list(groups=["friends"]), self.assertLogs("apps.accounts.views", "WARNING"):
            fragment = self.fragment(self.callback(self.claims(groups=["strangers"])))
        self.assertEqual(fragment, {"oidc_error": ["not_allowed"]})
        self.assertFalse(User.objects.exists())
        self.assertFalse(OIDCIdentity.objects.exists())

    def test_allowed_group_handles_a_string_claim_and_a_missing_claim(self):
        with self.allow_list(groups=["friends"]):
            self.signed_in(self.callback(self.claims(groups="friends")))
        self.client.cookies.clear()
        claims = self.claims(sub="user-456", preferred_username="heidi", email="heidi@example.com")
        del claims["groups"]
        with self.allow_list(groups=["friends"]), self.assertLogs("apps.accounts.views", "WARNING"):
            self.assertEqual(self.fragment(self.callback(claims)), {"oidc_error": ["not_allowed"]})

    def test_allowed_email_domain_needs_a_verified_email(self):
        with self.allow_list(domains=["example.com"]):
            self.signed_in(self.callback(self.claims(email="Grace@Example.com")))
        self.client.cookies.clear()
        with self.allow_list(domains=["example.com"]), self.assertLogs("apps.accounts.views", "WARNING"):
            unverified = self.callback(
                self.claims(sub="user-456", preferred_username="ivan", email="ivan@example.com", email_verified=False)
            )
        self.assertEqual(self.fragment(unverified), {"oidc_error": ["not_allowed"]})
        self.assertFalse(User.objects.filter(username="ivan").exists())

    def test_allowed_email_domain_refuses_other_domains_and_lookalikes(self):
        for email in ("mallory@evil.org", "mallory@example.com.evil.org", "mallory@notexample.com", "no-at-sign"):
            with self.subTest(email=email), self.allow_list(domains=["example.com"]), self.assertLogs(
                "apps.accounts.views", "WARNING"
            ):
                self.assertEqual(
                    self.fragment(self.callback(self.claims(sub=f"s-{email}", email=email))),
                    {"oidc_error": ["not_allowed"]},
                )
        self.assertFalse(User.objects.exists())

    def test_either_list_matching_is_enough(self):
        with self.allow_list(groups=["friends"], domains=["example.com"]):
            self.signed_in(self.callback(self.claims(email="grace@else.org", groups=["friends"])))
        self.client.cookies.clear()
        with self.allow_list(groups=["friends"], domains=["example.com"]):
            self.signed_in(self.callback(self.claims(sub="user-456", preferred_username="judy", groups=[])))

    def test_a_refused_user_who_already_has_an_account_is_still_refused(self):
        self.callback(self.claims())
        self.client.cookies.clear()
        with self.allow_list(groups=["friends"]), self.assertLogs("apps.accounts.views", "WARNING"):
            self.assertEqual(self.fragment(self.callback(self.claims())), {"oidc_error": ["not_allowed"]})
        self.assertIn(self.client.get(reverse("me")).status_code, (401, 403))

    @override_settings(AUTH_METHODS={"local"})
    def test_oidc_endpoints_404_when_disabled(self):
        self.assertEqual(self.client.get(reverse("oidc-login")).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.callback(self.claims()).status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(User.objects.exists())


class DevicePairingTests(APITestCase):
    start_url = "/api/devices/pair/start"
    approve_url = "/api/devices/pair/approve"
    poll_url = "/api/devices/pair/poll"

    def setUp(self):
        cache.clear()  # Throttle counters live in the cache.
        self.user = User.objects.create_user("owner", password="s3cure-pass-xyz")
        # The owner's phone: a signed-in browser session. Devices never share it.
        self.owner = APIClient()
        self.owner.force_login(self.user)

    def _start(self):
        response = self.client.post(self.start_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _approve(self, code):
        return self.owner.post(self.approve_url, {"code": code}, format="json")

    def _expire(self, code):
        PairingRequest.objects.filter(code=code).update(expires_at=timezone.now() - timedelta(seconds=1))

    def _pair_device(self):
        """Run the whole flow and return the raw device token the device would hold."""
        code = self._start()["code"]
        self._approve(code)
        return self.client.get(self.poll_url, {"code": code}).data["device_token"]

    def test_pair_start_returns_code_qr_expiry(self):
        data = self._start()

        self.assertEqual(len(data["code"]), 6)
        self.assertTrue(set(data["code"]) <= set(PAIRING_CODE_ALPHABET))
        parsed = urlparse(data["qr_url"])
        self.assertTrue(parsed.scheme and parsed.netloc)  # Absolute, so the phone can open it from the QR.
        self.assertEqual(parse_qs(parsed.query), {"code": [data["code"]]})
        self.assertGreater(parse_datetime(data["expires_at"]), timezone.now())
        pairing = PairingRequest.objects.get(code=data["code"])
        self.assertIsNone(pairing.approved_by)
        self.assertIsNone(pairing.device_token)
        self.assertFalse(pairing.consumed)
        self.assertEqual(pairing.qr_payload, data["qr_url"])

    def test_start_is_rate_limited_per_client(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"pair_start": "2/min"}):
            codes = [self.client.post(self.start_url).status_code for _ in range(3)]
        self.assertEqual(codes, [201, 201, 429])

    def test_start_purges_long_expired_requests(self):
        old = self._start()["code"]
        PairingRequest.objects.filter(code=old).update(expires_at=timezone.now() - timedelta(days=1))
        recent = self._start()["code"]
        PairingRequest.objects.filter(code=recent).update(expires_at=timezone.now() - timedelta(minutes=1))

        self._start()

        self.assertFalse(PairingRequest.objects.filter(code=old).exists())
        self.assertTrue(PairingRequest.objects.filter(code=recent).exists())

    def _approve_then_expire_without_polling(self):
        code = self._start()["code"]
        self._approve(code)
        raw = PairingRequest.objects.get(code=code).pending_token
        self.assertTrue(raw)  # Held until collected.
        self._expire(code)
        return code, raw

    def _assert_orphan_is_dead(self, code, raw):
        self.assertTrue(DeviceToken.objects.get().revoked)
        self.assertEqual(PairingRequest.objects.get(code=code).pending_token, "")
        response = self.client.get(reverse("me"), HTTP_AUTHORIZATION=f"Device {raw}")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_approved_but_never_polled_request_is_revoked_when_swept(self):
        code, raw = self._approve_then_expire_without_polling()

        expire_stale_pairings()

        self._assert_orphan_is_dead(code, raw)

    def test_sweep_task_revokes_uncollected_pairings(self):
        code, raw = self._approve_then_expire_without_polling()

        sweep_expired_pairings.call_local()

        self._assert_orphan_is_dead(code, raw)

    def test_sweep_leaves_live_and_collected_pairings_alone(self):
        live = self._start()["code"]
        self._approve(live)
        collected_raw = self._pair_device()
        collected = PairingRequest.objects.get(consumed=True)
        self._expire(collected.code)

        expire_stale_pairings()

        self.assertFalse(DeviceToken.objects.filter(revoked=True).exists())
        self.assertTrue(PairingRequest.objects.get(code=live).pending_token)
        response = self.client.get(reverse("me"), HTTP_AUTHORIZATION=f"Device {collected_raw}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_start_also_sweeps_uncollected_pairings(self):
        code, raw = self._approve_then_expire_without_polling()

        self._start()

        self._assert_orphan_is_dead(code, raw)

    def test_purging_old_rows_never_leaves_a_live_orphan_token(self):
        code, raw = self._approve_then_expire_without_polling()
        PairingRequest.objects.filter(code=code).update(expires_at=timezone.now() - timedelta(days=1))

        expire_stale_pairings()

        self.assertFalse(PairingRequest.objects.filter(code=code).exists())
        self.assertTrue(DeviceToken.objects.get().revoked)

    def test_device_token_admin_cannot_add_tokens(self):
        model_admin = admin.site._registry[DeviceToken]
        self.assertFalse(model_admin.has_add_permission(None))

    def test_approve_requires_auth_and_mints_token(self):
        code = self._start()["code"]

        anonymous = self.client.post(self.approve_url, {"code": code}, format="json")
        self.assertIn(anonymous.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertEqual(DeviceToken.objects.count(), 0)

        response = self._approve(code)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("device_token", response.data)  # The secret goes to the device, never the phone.
        device_token = DeviceToken.objects.get()
        self.assertEqual(device_token.user, self.user)
        self.assertFalse(device_token.revoked)
        pairing = PairingRequest.objects.get(code=code)
        self.assertEqual(pairing.approved_by, self.user)
        self.assertEqual(pairing.device_token, device_token)
        self.assertFalse(pairing.consumed)

    def test_approve_rejects_unknown_empty_and_already_approved_codes(self):
        self.assertEqual(self._approve("ZZZZZZ").status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self._approve("").status_code, status.HTTP_400_BAD_REQUEST)

        code = self._start()["code"]
        self.assertEqual(self._approve(code).status_code, status.HTTP_200_OK)
        self.assertEqual(self._approve(code).status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(DeviceToken.objects.count(), 1)

    def test_approve_ignores_case_and_whitespace(self):
        code = self._start()["code"]
        self.assertEqual(self._approve(f" {code.lower()} ").status_code, status.HTTP_200_OK)

    def test_device_token_cannot_approve_pairings(self):
        # Otherwise a lost device could mint replacement tokens that outlive its own revocation.
        raw = self._pair_device()
        second = self._start()["code"]

        response = self.client.post(
            self.approve_url, {"code": second}, format="json", HTTP_AUTHORIZATION=f"Device {raw}"
        )

        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertEqual(DeviceToken.objects.count(), 1)

    def test_poll_pending_then_returns_token_once(self):
        code = self._start()["code"]

        pending = self.client.get(self.poll_url, {"code": code})
        self.assertEqual(pending.status_code, status.HTTP_202_ACCEPTED)
        self.assertNotIn("device_token", pending.data)

        self._approve(code)
        done = self.client.get(self.poll_url, {"code": code})

        self.assertEqual(done.status_code, status.HTTP_200_OK)
        self.assertEqual(done.data["user"]["username"], "owner")
        self.assertEqual(done["Cache-Control"], "no-store")
        raw = done.data["device_token"]
        # Only a digest is kept; the raw secret authenticates but is not at rest.
        device_token = DeviceToken.objects.get()
        self.assertNotEqual(device_token.token_hash, raw)
        self.assertEqual(device_token.token_hash, hash_device_token(raw))
        pairing = PairingRequest.objects.get(code=code)
        self.assertTrue(pairing.consumed)
        self.assertEqual(pairing.pending_token, "")

        again = self.client.get(self.poll_url, {"code": code})
        self.assertEqual(again.status_code, status.HTTP_410_GONE)
        self.assertNotIn("device_token", again.data)

    def test_poll_unknown_or_missing_code(self):
        self.assertEqual(self.client.get(self.poll_url, {"code": "ZZZZZZ"}).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get(self.poll_url).status_code, status.HTTP_400_BAD_REQUEST)

    def test_approve_and_poll_are_rate_limited_per_client(self):
        code = self._start()["code"]
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"pair_code": "2/min"}):
            codes = [self.client.get(self.poll_url, {"code": code}).status_code for _ in range(3)]
            self.assertEqual(codes, [202, 202, 429])
            self.assertEqual(self._approve(code).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_expired_code_cannot_be_approved_or_polled(self):
        code = self._start()["code"]
        self._expire(code)

        self.assertEqual(self._approve(code).status_code, status.HTTP_410_GONE)
        self.assertEqual(self.client.get(self.poll_url, {"code": code}).status_code, status.HTTP_410_GONE)
        self.assertEqual(DeviceToken.objects.count(), 0)

    def test_approved_but_expired_request_never_hands_over_the_token(self):
        code = self._start()["code"]
        self._approve(code)
        self._expire(code)

        response = self.client.get(self.poll_url, {"code": code})

        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertNotIn("device_token", response.data)
        # The undelivered token is dead and its plaintext is gone.
        self.assertTrue(DeviceToken.objects.get().revoked)
        self.assertEqual(PairingRequest.objects.get(code=code).pending_token, "")

    def test_device_token_auth_accepted_and_revocable(self):
        raw = self._pair_device()
        me_url = reverse("me")

        response = self.client.get(me_url, HTTP_AUTHORIZATION=f"Device {raw}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.user.id)
        self.assertIsNotNone(DeviceToken.objects.get().last_used_at)

        DeviceToken.objects.update(revoked=True)
        revoked = self.client.get(me_url, HTTP_AUTHORIZATION=f"Device {raw}")
        self.assertEqual(revoked.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_device_token_cannot_write(self):
        # The handheld is browse/download-only: even a super_admin's paired device can't mutate.
        group, _ = Group.objects.get_or_create(name="super_admin")
        self.user.groups.add(group)
        rom = ROM.objects.create(title="Zelda", file=ContentFile(b"x" * 16, name="zelda.nes"), uploaded_by=self.user)
        playlist = Playlist.objects.create(name="Mine", created_by=self.user)
        raw = self._pair_device()
        auth = {"HTTP_AUTHORIZATION": f"Device {raw}"}

        attempts = [
            ("post", reverse("rom-list"), {"title": "New"}),
            ("patch", reverse("rom-detail", args=[rom.pk]), {"title": "Renamed"}),
            ("delete", reverse("rom-detail", args=[rom.pk]), None),
            ("post", reverse("rom-scrape-cover", args=[rom.pk]), None),
            ("post", reverse("playlist-list"), {"name": "New"}),
            ("patch", reverse("playlist-detail", args=[playlist.pk]), {"name": "Renamed"}),
            ("delete", reverse("playlist-detail", args=[playlist.pk]), None),
        ]
        for method, url, body in attempts:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, body, format="json", **auth)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        rom.refresh_from_db()
        playlist.refresh_from_db()
        self.assertEqual(rom.title, "Zelda")
        self.assertEqual(playlist.name, "Mine")

        # The same user's browser session is unaffected, so the restriction is the device's.
        regular = self.owner.patch(reverse("playlist-detail", args=[playlist.pk]), {"name": "Renamed"}, format="json")
        self.assertEqual(regular.status_code, status.HTTP_200_OK)

    def test_device_token_can_still_read(self):
        group, _ = Group.objects.get_or_create(name="readonly")
        self.user.groups.add(group)
        rom = ROM.objects.create(title="Zelda", file=ContentFile(b"x" * 16, name="zelda.nes"), uploaded_by=self.user)
        playlist = Playlist.objects.create(name="Mine", created_by=self.user)
        raw = self._pair_device()
        auth = {"HTTP_AUTHORIZATION": f"Device {raw}"}

        for url in (
            reverse("me"),
            reverse("rom-list"),
            reverse("rom-detail", args=[rom.pk]),
            reverse("rom-download", args=[rom.pk]),
            reverse("playlist-list"),
            reverse("playlist-detail", args=[playlist.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url, **auth)
                self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.options(reverse("rom-list"), **auth).status_code, status.HTTP_200_OK)

    def test_device_token_auth_rejects_garbage_and_inactive_users(self):
        me_url = reverse("me")
        for header in ("Device nonsense", "Device", "Device a b"):
            with self.subTest(header=header):
                response = self.client.get(me_url, HTTP_AUTHORIZATION=header)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        raw = self._pair_device()
        User.objects.update(is_active=False)
        response = self.client.get(me_url, HTTP_AUTHORIZATION=f"Device {raw}")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
