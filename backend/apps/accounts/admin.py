from django.contrib import admin

from .models import OIDCIdentity


@admin.register(OIDCIdentity)
class OIDCIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "issuer", "subject", "created_at")
    search_fields = ("user__username", "user__email", "subject")
