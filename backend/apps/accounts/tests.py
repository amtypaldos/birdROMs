from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseRedirect
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from apps.accounts.models import OIDCIdentity
from apps.accounts.services import set_role, user_role
from birdroms.auth_config import parse_allow_local_login, parse_auth_methods, parse_oidc_settings


class RegisterTests(APITestCase):
    url = reverse("register")

    def test_register_creates_readonly_user_and_returns_token(self):
        response = self.client.post(
            self.url,
            {"username": "alice", "email": "alice@example.com", "password": "s3cure-pass"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username="alice")
        self.assertTrue(user.groups.filter(name="readonly").exists())
        self.assertEqual(response.data["token"], Token.objects.get(user=user).key)
        self.assertEqual(response.data["user"]["username"], "alice")
        self.assertNotIn("password", response.data["user"])

    def test_register_rejects_short_password(self):
        response = self.client.post(
            self.url,
            {"username": "bob", "email": "bob@example.com", "password": "short"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)
        self.assertFalse(User.objects.filter(username="bob").exists())


class LoginTests(APITestCase):
    url = reverse("login")

    def setUp(self):
        self.user = User.objects.create_user(username="carol", password="correct-horse")

    def test_login_with_valid_credentials_returns_token(self):
        response = self.client.post(self.url, {"username": "carol", "password": "correct-horse"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["token"], Token.objects.get(user=self.user).key)
        self.assertEqual(response.data["user"]["username"], "carol")

    def test_login_with_invalid_credentials_returns_400(self):
        response = self.client.post(self.url, {"username": "carol", "password": "wrong-password"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("token", response.data)


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
        self.assertEqual(response.data, {"methods": ["local"]})

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

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=False, OIDC=OIDC_TEST_CONFIG)
    def test_local_endpoints_404_when_disabled(self):
        self.assertEqual(self.login().status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.register().status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(User.objects.filter(username="erin").exists())

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=True, OIDC=OIDC_TEST_CONFIG)
    def test_allow_local_login_force_enables_local_endpoints(self):
        self.assertEqual(self.login().status_code, status.HTTP_200_OK)
        self.assertEqual(self.register().status_code, status.HTTP_201_CREATED)

    @override_settings(AUTH_METHODS={"local", "oidc"}, ALLOW_LOCAL_LOGIN=False, OIDC=OIDC_TEST_CONFIG)
    def test_local_endpoints_work_when_both_enabled(self):
        self.assertEqual(self.login().status_code, status.HTTP_200_OK)


class MeTests(APITestCase):
    url = reverse("me")

    def test_requires_authentication(self):
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_returns_user_and_role(self):
        user = User.objects.create_user(username="frank", email="frank@example.com", password="pw-123456")
        set_role(user, "readonly")
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

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
        self.assertEqual(response.status_code, 302)
        location = response["Location"]
        self.assertTrue(location.startswith("http://spa.example/#"), location)
        return parse_qs(urlparse(location).fragment)

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

    def test_first_login_provisions_readonly_user_and_returns_api_token(self):
        fragment = self.fragment(self.callback(self.claims()))

        user = User.objects.get(username="grace")
        self.assertEqual(user.email, "grace@example.com")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user_role(user), "readonly")
        self.assertEqual(OIDCIdentity.objects.get(user=user).subject, "user-123")
        self.assertEqual(fragment["oidc_token"], [Token.objects.get(user=user).key])

        # The token works against the existing DRF API.
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {fragment['oidc_token'][0]}")
        self.assertEqual(self.client.get(reverse("me")).data["role"], "readonly")
        self.assertEqual(self.client.get("/api/roms/").status_code, status.HTTP_200_OK)

    def test_admin_group_claim_maps_to_super_admin(self):
        self.fragment(self.callback(self.claims(groups=["birdroms-admins", "other"])))
        self.assertEqual(user_role(User.objects.get(username="grace")), "super_admin")

    def test_groups_claim_fetched_from_userinfo_when_missing_from_id_token(self):
        claims = self.claims()
        del claims["groups"]
        self.fragment(self.callback(claims, userinfo={"sub": "user-123", "groups": ["birdroms-admins"]}))
        self.assertEqual(user_role(User.objects.get(username="grace")), "super_admin")

    @override_settings(OIDC={**OIDC_TEST_CONFIG, "GROUPS_CLAIM": "roles"})
    def test_custom_groups_claim(self):
        self.fragment(self.callback(self.claims(roles="birdroms-admins")))
        self.assertEqual(user_role(User.objects.get(username="grace")), "super_admin")

    def test_returning_user_matches_on_subject_and_role_is_resynced(self):
        self.callback(self.claims(groups=["birdroms-admins"]))
        self.fragment(self.callback(self.claims(preferred_username="renamed", email="new@example.com")))

        self.assertEqual(User.objects.count(), 1)
        user = User.objects.get()
        self.assertEqual(user.username, "grace")
        self.assertEqual(user.email, "new@example.com")
        self.assertEqual(user_role(user), "readonly")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["readonly"])

    def test_username_collision_gets_suffix_and_does_not_hijack_local_account(self):
        local = User.objects.create_user(username="grace", email="grace@example.com", password="pw-123456")

        self.fragment(self.callback(self.claims()))

        self.assertEqual(User.objects.count(), 2)
        self.assertFalse(hasattr(User.objects.get(pk=local.pk), "oidc_identity"))
        self.assertTrue(User.objects.filter(username="grace-2").exists())

    @override_settings(OIDC={**OIDC_TEST_CONFIG, "LINK_BY_EMAIL": True})
    def test_link_by_verified_email_when_enabled(self):
        local = User.objects.create_user(username="gracelocal", email="Grace@example.com", password="pw-123456")
        self.fragment(self.callback(self.claims()))
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(OIDCIdentity.objects.get().user, local)

    @override_settings(OIDC={**OIDC_TEST_CONFIG, "LINK_BY_EMAIL": True})
    def test_unverified_email_is_never_linked(self):
        User.objects.create_user(username="gracelocal", email="grace@example.com", password="pw-123456")
        self.fragment(self.callback(self.claims(email_verified=False)))
        self.assertEqual(User.objects.count(), 2)

    def test_inactive_user_gets_no_token(self):
        self.callback(self.claims())
        User.objects.filter(username="grace").update(is_active=False)
        Token.objects.all().delete()

        fragment = self.fragment(self.callback(self.claims()))

        self.assertNotIn("oidc_token", fragment)
        self.assertIn("oidc_error", fragment)
        self.assertFalse(Token.objects.exists())

    def test_provider_error_redirects_with_error(self):
        fragment = self.fragment(self.callback(self.claims(), query="?error=access_denied"))
        self.assertEqual(fragment["oidc_error"], ["access_denied"])
        self.assertFalse(User.objects.exists())

    def test_failed_token_exchange_redirects_with_generic_error(self):
        client = fake_oidc_client({})
        client.authorize_access_token.side_effect = Exception("mismatching_state")
        with mock.patch("apps.accounts.views.get_oidc_client", return_value=client), self.assertLogs(
            "apps.accounts.views", "WARNING"
        ):
            fragment = self.fragment(self.client.get(self.callback_url + "?code=abc&state=bad"))
        self.assertIn("oidc_error", fragment)
        self.assertNotIn("mismatching_state", fragment["oidc_error"][0])
        self.assertFalse(User.objects.exists())

    @override_settings(AUTH_METHODS={"local"})
    def test_oidc_endpoints_404_when_disabled(self):
        self.assertEqual(self.client.get(reverse("oidc-login")).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.callback(self.claims()).status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(User.objects.exists())
