from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.invites import accept_invite, create_invite, find_pending_invite
from apps.accounts.models import Invite, hash_invite_token
from apps.accounts.services import registration_enabled, set_role, user_role

GOOD_PASSWORD = "s3cure-pass-xyz"


class InviteServiceTests(APITestCase):
    def test_only_a_hash_of_the_token_is_stored(self):
        invite, raw = create_invite()

        self.assertEqual(invite.token_hash, hash_invite_token(raw))
        self.assertNotIn(raw, [str(value) for value in vars(invite).values()])
        self.assertEqual(Invite.objects.filter(token_hash=raw).count(), 0)

    def test_defaults_to_readonly_and_the_configured_ttl(self):
        with override_settings(INVITE_TTL_DAYS=3):
            invite, _ = create_invite()
        self.assertEqual(invite.role, "readonly")
        self.assertAlmostEqual(invite.expires_at, timezone.now() + timedelta(days=3), delta=timedelta(seconds=5))

    def test_default_ttl_is_seven_days(self):
        invite, _ = create_invite()
        self.assertAlmostEqual(invite.expires_at, timezone.now() + timedelta(days=7), delta=timedelta(seconds=5))

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(ValueError):
            create_invite(role="root")
        self.assertEqual(Invite.objects.count(), 0)

    def test_tokens_are_random_and_unguessable_lookups_fail(self):
        _, a = create_invite()
        _, b = create_invite()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 40)
        self.assertIsNone(find_pending_invite("nope"))
        self.assertIsNone(find_pending_invite(""))
        self.assertIsNone(find_pending_invite(None))

    def test_status_covers_pending_used_expired_revoked(self):
        invite, _ = create_invite()
        self.assertEqual(invite.status(), "pending")
        self.assertEqual(invite.status(now=invite.expires_at + timedelta(seconds=1)), "expired")
        invite.revoked_at = timezone.now()
        self.assertEqual(invite.status(), "revoked")
        invite.used_at = timezone.now()
        self.assertEqual(invite.status(), "used")

    def test_accept_is_single_use(self):
        _, raw = create_invite(role="super_admin")
        user = accept_invite(raw, "dave", GOOD_PASSWORD)
        self.assertEqual(user_role(user), "super_admin")
        self.assertIsNone(find_pending_invite(raw))


class InviteAdminApiTests(APITestCase):
    url = reverse("invites")

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user("boss", password=GOOD_PASSWORD)
        set_role(self.admin, "super_admin")
        self.reader = User.objects.create_user("reader", password=GOOD_PASSWORD)
        set_role(self.reader, "readonly")

    def test_only_super_admins_can_create_or_list(self):
        self.assertIn(self.client.post(self.url, {}, format="json").status_code, (401, 403))
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.post(self.url, {}, format="json").status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(Invite.objects.count(), 0)

    def test_device_tokens_cannot_manage_invites(self):
        from apps.accounts.models import DeviceToken

        _, raw = DeviceToken.mint(self.admin)
        self.assertIn(self.client.get(self.url, HTTP_AUTHORIZATION=f"Device {raw}").status_code, (401, 403))

    def test_create_returns_the_link_once_with_defaults(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["role"], "readonly")
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["path"], f"/invite/{body['token']}")
        self.assertEqual(body["url"], f"http://testserver{body['path']}")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(Invite.objects.get().created_by, self.admin)
        self.assertTrue(find_pending_invite(body["token"]))

    def test_create_accepts_role_expiry_and_label(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            self.url, {"role": "super_admin", "expires_in_days": 2, "label": "Sam"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        invite = Invite.objects.get()
        self.assertEqual((invite.role, invite.label), ("super_admin", "Sam"))
        self.assertAlmostEqual(invite.expires_at, timezone.now() + timedelta(days=2), delta=timedelta(seconds=5))

    def test_create_accepts_the_uploader_role(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(self.url, {"role": "uploader"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Invite.objects.get().role, "uploader")

    def test_create_rejects_bad_role_and_expiry(self):
        self.client.force_authenticate(self.admin)
        for payload in ({"role": "root"}, {"expires_in_days": 0}, {"expires_in_days": 4000}, {"expires_in_days": "x"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(self.url, payload, format="json").status_code, 400)
        self.assertEqual(Invite.objects.count(), 0)

    def test_list_shows_every_status_and_never_a_token(self):
        pending, raw = create_invite(self.admin)
        expired, _ = create_invite(self.admin)
        Invite.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(days=1))
        revoked, _ = create_invite(self.admin)
        Invite.objects.filter(pk=revoked.pk).update(revoked_at=timezone.now())
        used, used_raw = create_invite(self.admin)
        accept_invite(used_raw, "friend", GOOD_PASSWORD)

        self.client.force_authenticate(self.admin)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        statuses = {row["id"]: row["status"] for row in response.json()}
        self.assertEqual(
            statuses, {pending.pk: "pending", expired.pk: "expired", revoked.pk: "revoked", used.pk: "used"}
        )
        text = response.content.decode()
        self.assertNotIn(raw, text)
        self.assertNotIn(pending.token_hash, text)
        used_row = next(row for row in response.json() if row["id"] == used.pk)
        self.assertEqual(used_row["used_by"], "friend")

    def test_revoke_pending_invite(self):
        invite, raw = create_invite(self.admin)
        self.client.force_authenticate(self.admin)

        response = self.client.delete(reverse("invite-revoke", args=[invite.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "revoked")
        self.assertIsNone(find_pending_invite(raw))

    def test_cannot_revoke_a_used_invite_and_readers_cannot_revoke(self):
        invite, raw = create_invite(self.admin)
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.delete(reverse("invite-revoke", args=[invite.pk])).status_code, 403)
        accept_invite(raw, "friend", GOOD_PASSWORD)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.delete(reverse("invite-revoke", args=[invite.pk])).status_code, 409)
        self.assertEqual(self.client.delete(reverse("invite-revoke", args=[9999])).status_code, 404)

    def test_session_admin_needs_a_csrf_token_to_create(self):
        client = APIClient(enforce_csrf_checks=True)
        client.login(username="boss", password=GOOD_PASSWORD)
        self.assertEqual(client.post(self.url, {}, format="json").status_code, 403)
        self.assertEqual(Invite.objects.count(), 0)

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=False)
    def test_invites_404_when_local_login_is_off(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {}, format="json").status_code, 404)
        self.assertEqual(self.client.post(reverse("invite-check"), {"token": "x"}, format="json").status_code, 404)
        self.assertEqual(self.client.post(reverse("invite-accept"), {}, format="json").status_code, 404)


class InviteAcceptApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user("boss", password=GOOD_PASSWORD)
        set_role(self.admin, "super_admin")
        self.invite, self.raw = create_invite(self.admin)

    def check(self, token):
        return self.client.post(reverse("invite-check"), {"token": token}, format="json")

    def accept(self, **overrides):
        payload = {"token": self.raw, "username": "friend", "password": GOOD_PASSWORD, **overrides}
        return self.client.post(reverse("invite-accept"), payload, format="json")

    def test_check_accepts_a_pending_token(self):
        self.assertEqual(self.check(self.raw).json(), {"valid": True})

    def test_check_refuses_unknown_expired_used_and_revoked_the_same_way(self):
        _, expired_raw = create_invite()
        Invite.objects.filter(token_hash=hash_invite_token(expired_raw)).update(expires_at=timezone.now())
        _, revoked_raw = create_invite()
        Invite.objects.filter(token_hash=hash_invite_token(revoked_raw)).update(revoked_at=timezone.now())
        _, used_raw = create_invite()
        accept_invite(used_raw, "someone", GOOD_PASSWORD)

        bodies = {self.check(token).content for token in ("unknown", expired_raw, revoked_raw, used_raw, "")}

        self.assertEqual(len(bodies), 1)
        self.assertEqual(self.check("unknown").status_code, 404)

    def test_accept_creates_the_account_consumes_the_invite_and_signs_in(self):
        response = self.accept(email="friend@example.com")

        self.assertEqual(response.status_code, 201, response.content)
        user = User.objects.get(username="friend")
        self.assertEqual(user.email, "friend@example.com")
        self.assertTrue(user.check_password(GOOD_PASSWORD))
        self.assertEqual(user_role(user), "readonly")
        self.invite.refresh_from_db()
        self.assertEqual((self.invite.status(), self.invite.used_by), ("used", user))
        self.assertNotIn("token", response.json())
        self.assertEqual(self.client.get(reverse("me")).json()["username"], "friend")  # signed in by cookie

    def test_invite_works_while_self_registration_is_closed(self):
        self.assertFalse(registration_enabled())
        self.assertEqual(self.client.post(reverse("register"), {}, format="json").status_code, 404)
        self.assertEqual(self.accept().status_code, 201)

    def test_accept_gives_the_invited_role(self):
        _, raw = create_invite(role="super_admin")
        self.assertEqual(self.accept(token=raw, username="deputy").status_code, 201)
        self.assertEqual(user_role(User.objects.get(username="deputy")), "super_admin")

    def test_accept_gives_the_uploader_role(self):
        invite, raw = create_invite(role="uploader")
        self.assertEqual(invite.role, "uploader")
        self.assertEqual(self.accept(token=raw, username="helper").status_code, 201)
        self.assertEqual(user_role(User.objects.get(username="helper")), "uploader")

    def test_second_use_is_refused(self):
        self.assertEqual(self.accept().status_code, 201)
        self.client.logout()
        second = self.accept(username="other")
        self.assertEqual(second.status_code, 404)
        self.assertFalse(User.objects.filter(username="other").exists())

    def test_expired_and_revoked_invites_create_nothing(self):
        Invite.objects.filter(pk=self.invite.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.accept().status_code, 404)
        Invite.objects.filter(pk=self.invite.pk).update(expires_at=timezone.now() + timedelta(days=1), revoked_at=timezone.now())
        self.assertEqual(self.accept().status_code, 404)
        self.assertFalse(User.objects.filter(username="friend").exists())

    def test_weak_password_is_rejected_and_the_invite_stays_usable(self):
        for password in ("short", "password", "12345678", "friend123"):
            with self.subTest(password=password):
                response = self.accept(password=password)
                self.assertEqual(response.status_code, 400)
                self.assertIn("password", response.json())
        self.assertEqual(find_pending_invite(self.raw), self.invite)
        self.assertEqual(self.accept().status_code, 201)

    def test_taken_username_is_rejected_case_insensitively_and_the_invite_stays_usable(self):
        response = self.accept(username="BOSS")
        self.assertEqual(response.status_code, 400)
        self.assertIn("username", response.json())
        self.assertEqual(User.objects.filter(username__iexact="boss").count(), 1)
        self.assertEqual(find_pending_invite(self.raw), self.invite)

    def test_invalid_username_characters_are_rejected(self):
        self.assertEqual(self.accept(username="bad name!").status_code, 400)

    def test_accept_requires_a_csrf_token(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.post(
            reverse("invite-accept"), {"token": self.raw, "username": "friend", "password": GOOD_PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(find_pending_invite(self.raw), self.invite)

    def test_accept_is_rate_limited(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"invite": "2/hour"}):
            codes = [self.accept(token="wrong").status_code for _ in range(3)]
        self.assertEqual(codes, [404, 404, 429])

    def test_check_is_rate_limited(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"invite": "2/hour"}):
            codes = [self.check("wrong").status_code for _ in range(3)]
        self.assertEqual(codes, [404, 404, 429])


class CreateInviteCommandTests(APITestCase):
    def run_command(self, *args):
        out, err = StringIO(), StringIO()
        call_command("create_invite", *args, stdout=out, stderr=err)
        return out.getvalue().strip(), err.getvalue()

    def test_prints_a_working_link(self):
        link, _ = self.run_command("--base-url", "https://roms.example.com/")

        self.assertTrue(link.startswith("https://roms.example.com/invite/"))
        invite = find_pending_invite(link.rsplit("/", 1)[1])
        self.assertEqual(invite.role, "readonly")

    def test_role_days_and_label_options(self):
        link, _ = self.run_command("--role", "super_admin", "--days", "1", "--label", "Sam", "--base-url", "http://x")
        invite = find_pending_invite(link.rsplit("/", 1)[1])
        self.assertEqual((invite.role, invite.label), ("super_admin", "Sam"))
        self.assertAlmostEqual(invite.expires_at, timezone.now() + timedelta(days=1), delta=timedelta(seconds=5))

    def test_uploader_role_option(self):
        link, _ = self.run_command("--role", "uploader", "--base-url", "http://x")
        self.assertEqual(find_pending_invite(link.rsplit("/", 1)[1]).role, "uploader")

    def test_unknown_role_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_command("--role", "root")

    def test_default_base_url_comes_from_the_trusted_origin(self):
        with override_settings(CSRF_TRUSTED_ORIGINS=["https://roms.example.com"]):
            link, _ = self.run_command()
        self.assertTrue(link.startswith("https://roms.example.com/invite/"))

    @override_settings(AUTH_METHODS={"oidc"}, ALLOW_LOCAL_LOGIN=False)
    def test_refuses_when_local_login_is_off(self):
        with self.assertRaises(CommandError):
            self.run_command()
        self.assertEqual(Invite.objects.count(), 0)

    def test_rejects_zero_days(self):
        with self.assertRaises(CommandError):
            self.run_command("--days", "0")
