from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.invites import INVITE_PATH, create_invite
from apps.accounts.services import READONLY, ROLE_GROUPS, local_login_enabled


class Command(BaseCommand):
    help = "Create an invite link for a new local account (the raw token is printed once and not stored)."

    def add_arguments(self, parser):
        parser.add_argument("--role", choices=ROLE_GROUPS, default=READONLY, help="Role the new account gets.")
        parser.add_argument("--days", type=int, help="Days the link stays valid (default: INVITE_TTL_DAYS).")
        parser.add_argument("--label", default="", help="A note to recognise the invite by, e.g. the friend's name.")
        parser.add_argument("--base-url", help="Site address for the printed link, e.g. https://roms.example.com.")

    def handle(self, *args, **options):
        if not local_login_enabled():
            raise CommandError("Local login is disabled (AUTH_METHODS has no 'local'), so invites would be unusable.")
        days = options["days"]
        if days is not None and days < 1:
            raise CommandError("--days must be at least 1.")
        invite, raw = create_invite(role=options["role"], ttl_days=days, label=options["label"])
        base = (options["base_url"] or self._default_base_url()).rstrip("/")
        self.stdout.write(f"{base}{INVITE_PATH.format(token=raw)}")
        self.stderr.write(
            f"Invite {invite.pk} ({invite.role}) expires {invite.expires_at:%Y-%m-%d %H:%M} UTC; it works once."
        )

    @staticmethod
    def _default_base_url():
        origins = settings.CSRF_TRUSTED_ORIGINS
        if origins:
            return origins[0]
        return f"http://{settings.ALLOWED_HOSTS[0]}"
