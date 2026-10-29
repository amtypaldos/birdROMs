from django.contrib import admin

from .models import DeviceToken, Invite, OIDCIdentity, RegistrationSettings


@admin.register(OIDCIdentity)
class OIDCIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "issuer", "subject", "created_at")
    search_fields = ("user__username", "user__email", "subject")


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    """Lets an admin cut off a lost device by ticking `revoked`."""

    list_display = ("name", "user", "created_at", "last_used_at", "revoked")
    list_filter = ("revoked",)
    search_fields = ("name", "user__username")
    readonly_fields = ("created_at", "last_used_at")

    def has_add_permission(self, request):
        # Tokens only come from the pairing flow; a hand-made row would have no usable secret.
        return False


@admin.register(RegistrationSettings)
class RegistrationSettingsAdmin(admin.ModelAdmin):
    """The single settings row: tick `allow_registration` to open sign-up (unless the env var overrides it)."""

    list_display = ("__str__", "allow_registration")

    def has_add_permission(self, request):
        return not RegistrationSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    """Invites are made with `manage.py create_invite` or the web UI (the raw token only exists then).

    The admin lists them and can revoke a pending one by setting `revoked_at`; it can't add one, because a
    hand-made row would have no token anyone knows.
    """

    list_display = ("label", "role", "status_display", "created_by", "created_at", "expires_at", "used_by")
    list_filter = ("role",)
    search_fields = ("label", "created_by__username", "used_by__username")
    readonly_fields = ("token_hash", "created_by", "created_at", "expires_at", "used_at", "used_by")

    @admin.display(description="status")
    def status_display(self, invite):
        return invite.status()

    def has_add_permission(self, request):
        return False
