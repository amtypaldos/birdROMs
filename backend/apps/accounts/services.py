import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.db import transaction
from django.utils import timezone

from .models import DeviceToken, OIDCIdentity, PairingRequest, RegistrationSettings

SUPER_ADMIN = "super_admin"
READONLY = "readonly"
ROLE_GROUPS = (SUPER_ADMIN, READONLY)

# Expired pairing rows are kept this long so a late poll still reads "gone" rather than "unknown".
PAIRING_RETENTION = timedelta(hours=1)

_oidc_clients = {}


def local_login_enabled() -> bool:
    return "local" in settings.AUTH_METHODS or settings.ALLOW_LOCAL_LOGIN


def registration_enabled() -> bool:
    """Self-registration is open only with local login on and the setting open.

    A set `ALLOW_REGISTRATION` env var (True/False) wins; when unset (None) the Django-admin
    `RegistrationSettings` checkbox decides, and it defaults to closed.
    """
    if not local_login_enabled():
        return False
    if settings.ALLOW_REGISTRATION is not None:
        return settings.ALLOW_REGISTRATION
    return RegistrationSettings.load().allow_registration


def oidc_enabled() -> bool:
    return "oidc" in settings.AUTH_METHODS


def enabled_methods() -> list:
    methods = []
    if local_login_enabled():
        methods.append("local")
    if oidc_enabled():
        methods.append("oidc")
    return methods


def user_role(user):
    """The user's birdROMs role: `super_admin`, `readonly`, or None if they have neither."""
    if user.is_superuser or user.groups.filter(name=SUPER_ADMIN).exists():
        return SUPER_ADMIN
    if user.groups.filter(name=READONLY).exists():
        return READONLY
    return None


def set_role(user, role):
    """Put the user in exactly one role group."""
    user.groups.remove(*Group.objects.filter(name__in=ROLE_GROUPS).exclude(name=role))
    group, _ = Group.objects.get_or_create(name=role)
    user.groups.add(group)


def get_oidc_client():
    """An authlib client for the configured provider, cached per config (discovery is fetched lazily)."""
    from authlib.integrations.django_client import OAuth

    config = settings.OIDC
    key = (config["DISCOVERY_URL"], config["CLIENT_ID"], config["CLIENT_SECRET"], config["SCOPES"])
    if key not in _oidc_clients:
        oauth = OAuth()
        _oidc_clients[key] = oauth.register(
            name="birdroms_oidc",
            server_metadata_url=config["DISCOVERY_URL"],
            client_id=config["CLIENT_ID"],
            client_secret=config["CLIENT_SECRET"],
            client_kwargs={"scope": config["SCOPES"], "code_challenge_method": "S256"},
        )
    return _oidc_clients[key]


def _claim_list(value):
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value or []]


def oidc_login_allowed(claims) -> bool:
    """Whether the allow-list (if any) admits this user. Fails closed once either list is set.

    `OIDC_ALLOWED_GROUPS` matches the groups claim; `OIDC_ALLOWED_EMAIL_DOMAINS` matches the part after the
    `@` of the email, and only when the provider marks it verified. A user matching neither is refused.
    With neither list set, every user the provider authenticates is allowed.
    """
    config = settings.OIDC
    allowed_groups, allowed_domains = config["ALLOWED_GROUPS"], config["ALLOWED_EMAIL_DOMAINS"]
    if not allowed_groups and not allowed_domains:
        return True
    if allowed_groups and set(allowed_groups) & set(_claim_list(claims.get(config["GROUPS_CLAIM"]))):
        return True
    email = str(claims.get("email") or "")
    if allowed_domains and claims.get("email_verified") is True and "@" in email:
        return email.rsplit("@", 1)[1].lower() in allowed_domains
    return False


def role_from_claims(claims):
    config = settings.OIDC
    admin_group = config["ADMIN_GROUP"]
    groups = claims.get(config["GROUPS_CLAIM"]) or []
    if isinstance(groups, str):
        groups = [groups]
    return SUPER_ADMIN if admin_group and admin_group in groups else READONLY


def _unique_username(claims):
    email = claims.get("email") or ""
    base = claims.get("preferred_username") or email.split("@")[0] or f"oidc-{claims['sub']}"
    base = re.sub(r"[^\w.@+-]", "_", base)[:140] or "oidc-user"
    candidate, n = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


@transaction.atomic
def provision_oidc_user(claims):
    """
    Find or create the Django user for a verified set of OIDC claims and sync their role.

    Users are matched on the stable `(issuer, sub)` pair. With `OIDC_LINK_BY_EMAIL`, a first
    login may instead attach to an existing user with the same email, but only when the provider
    marks that email as verified; the account's local password is then revoked (which also ends
    its browser sessions), since local sign-up does not prove ownership of the address. The role group is
    re-synced from the claims on every login so that removing someone from `OIDC_ADMIN_GROUP` at the provider takes effect.
    """
    config = settings.OIDC
    issuer = claims.get("iss") or config["ISSUER"]
    subject = str(claims["sub"])
    email = claims.get("email") or ""

    identity = OIDCIdentity.objects.select_related("user").filter(issuer=issuer, subject=subject).first()
    if identity:
        user = identity.user
    else:
        user = None
        if config["LINK_BY_EMAIL"] and email and claims.get("email_verified") is True:
            matches = list(User.objects.filter(email__iexact=email)[:2])
            if len(matches) == 1 and not hasattr(matches[0], "oidc_identity"):
                user = matches[0]
                # Local sign-up never verifies email, so whoever created this account may not own
                # the address. Take it over: drop any password they hold (the password
                # change also invalidates their sessions), leaving SSO as the way in.
                user.set_unusable_password()
                user.save(update_fields=["password"])
        if user is None:
            user = User(username=_unique_username(claims), email=email)
            user.set_unusable_password()
            user.save()
        OIDCIdentity.objects.create(user=user, issuer=issuer, subject=subject)

    if not user.is_active:
        return user
    if email and user.email != email:
        user.email = email
        user.save(update_fields=["email"])
    if not user.is_superuser:
        set_role(user, role_from_claims(claims))
    return user


def expire_stale_pairings(now=None):
    """Kill pairings that were approved but never collected, and drop long-expired rows.

    An approved request holds a live device token and its raw secret until the device polls. Once the
    request has expired nobody can collect it, so the token is revoked and the secret blanked. Runs
    from the periodic `sweep_expired_pairings` task and opportunistically on `pair/start`.
    """
    now = now or timezone.now()
    stale = PairingRequest.objects.filter(expires_at__lte=now, consumed=False, device_token__isnull=False)
    DeviceToken.objects.filter(pk__in=stale.values("device_token")).update(revoked=True)
    stale.exclude(pending_token="").update(pending_token="")
    # Tokens were revoked above, so deleting the rows can't orphan a live credential.
    PairingRequest.objects.filter(expires_at__lt=now - PAIRING_RETENTION).delete()
