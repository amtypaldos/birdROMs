import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class OIDCIdentity(models.Model):
    """Links a Django user to the stable `(issuer, sub)` pair of an OIDC provider account."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="oidc_identity")
    issuer = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["issuer", "subject"], name="unique_oidc_identity")]

    def __str__(self):
        return f"{self.user} <{self.issuer} {self.subject}>"


class RegistrationSettings(models.Model):
    """Singleton (pk=1) editable in Django admin: may anyone self-register?

    A non-empty `ALLOW_REGISTRATION` environment variable overrides this; see `registration_enabled()`.
    """

    allow_registration = models.BooleanField(
        default=False,
        help_text=(
            "Let visitors create their own (read-only) account from the login page. "
            "A non-empty ALLOW_REGISTRATION environment variable overrides this checkbox. "
            "Registration also requires local login to be enabled."
        ),
    )

    class Meta:
        verbose_name = "registration settings"
        verbose_name_plural = "registration settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Registration settings"


# No 0/O or 1/I/L, so a code read off a handheld screen can be typed on a phone without mix-ups.
PAIRING_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PAIRING_CODE_LENGTH = 6


def hash_device_token(raw_token: str) -> str:
    """The digest stored for a device token. The token is 256 random bits, so a plain SHA-256 is enough."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_pairing_code() -> str:
    return "".join(secrets.choice(PAIRING_CODE_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))


class DeviceToken(models.Model):
    """A revocable credential for one paired handheld, sent as `Authorization: Device <token>`.

    Only the SHA-256 digest is stored; the raw secret is shown to the device once, at pairing.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="device_tokens")
    name = models.CharField(max_length=100, default="Handheld")
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)

    @classmethod
    def mint(cls, user, name="Handheld"):
        """Create a token for `user`; returns `(device_token, raw_secret)`."""
        raw = secrets.token_urlsafe(32)
        return cls.objects.create(user=user, name=name, token_hash=hash_device_token(raw)), raw

    def __str__(self):
        return f"{self.name} ({self.user})"


class PairingRequest(models.Model):
    """A short-lived, single-use handshake between a handheld (shows the code) and the owner's phone."""

    code = models.CharField(max_length=PAIRING_CODE_LENGTH, unique=True)
    qr_payload = models.URLField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    device_token = models.ForeignKey(DeviceToken, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # The raw secret, held only between approval and the device's one successful poll (then cleared).
    pending_token = models.CharField(max_length=64, blank=True, default="")
    consumed = models.BooleanField(default=False)

    def is_expired(self):
        return self.expires_at <= timezone.now()

    def __str__(self):
        return self.code


def hash_invite_token(raw_token: str) -> str:
    """The digest stored for an invite token (256 random bits, so a plain SHA-256 is enough)."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


class Invite(models.Model):
    """A single-use link an admin sends to a friend so they can create a local account.

    Only the SHA-256 digest of the token is stored; the raw token is shown to the admin once, at creation.
    """

    ROLE_CHOICES = [("readonly", "readonly"), ("member", "member"), ("super_admin", "super_admin")]

    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="readonly")
    label = models.CharField(max_length=100, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def status(self, now=None):
        """`used`, `revoked`, `expired` or `pending`."""
        now = now or timezone.now()
        if self.used_at is not None:
            return "used"
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at <= now:
            return "expired"
        return "pending"

    def __str__(self):
        return f"invite {self.pk} ({self.role}, {self.status()})"
