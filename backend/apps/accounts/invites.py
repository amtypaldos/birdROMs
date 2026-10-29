"""Invite links: how new local users join. There is no open sign-up.

An admin creates an invite (web UI or `manage.py create_invite`); the raw token appears once, inside the
`/invite/<token>` link. Only its SHA-256 digest is stored, and a token works once, before it expires.
"""

import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Invite, hash_invite_token
from .services import READONLY, ROLE_GROUPS, set_role

INVITE_PATH = "/invite/{token}"


class InviteUnavailable(Exception):
    """The token is unknown, expired, used or revoked (deliberately indistinguishable to the caller)."""


class UsernameTaken(Exception):
    pass


def create_invite(created_by=None, role=READONLY, ttl_days=None, label=""):
    """Create an invite; returns `(invite, raw_token)`. The raw token is not recoverable afterwards."""
    if role not in ROLE_GROUPS:
        raise ValueError(f"Unknown role {role!r}.")
    days = settings.INVITE_TTL_DAYS if ttl_days is None else ttl_days
    raw = secrets.token_urlsafe(32)
    invite = Invite.objects.create(
        token_hash=hash_invite_token(raw),
        role=role,
        label=label,
        created_by=created_by,
        expires_at=timezone.now() + timedelta(days=days),
    )
    return invite, raw


def find_pending_invite(raw_token, for_update=False):
    """The pending invite for a raw token, or None. Compares digests in constant time."""
    digest = hash_invite_token(str(raw_token or ""))
    queryset = Invite.objects.select_for_update() if for_update else Invite.objects
    invite = queryset.filter(token_hash=digest).first()
    if invite is None or not hmac.compare_digest(invite.token_hash, digest) or invite.status() != "pending":
        return None
    return invite


def accept_invite(raw_token, username, password, email=""):
    """Create the account an invite entitles, consume the invite, and return the new user.

    Everything happens in one transaction with the invite row locked, so two people racing on one link
    cannot both get an account, and a failure (for example a taken username) leaves the invite pending.
    """
    with transaction.atomic():
        invite = find_pending_invite(raw_token, for_update=True)
        if invite is None:
            raise InviteUnavailable()
        if User.objects.filter(username__iexact=username).exists():
            raise UsernameTaken()
        try:
            with transaction.atomic():
                user = User.objects.create_user(username=username, email=email, password=password)
        except IntegrityError:
            raise UsernameTaken()
        set_role(user, invite.role)
        invite.used_at = timezone.now()
        invite.used_by = user
        invite.save(update_fields=["used_at", "used_by"])
    return user
