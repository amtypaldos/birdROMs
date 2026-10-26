from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase


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
