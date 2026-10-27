from django.contrib import admin

from .models import DeviceToken, OIDCIdentity


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
