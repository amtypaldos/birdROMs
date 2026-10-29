from django.contrib import admin

from .models import DeviceToken, OIDCIdentity, RegistrationSettings


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
