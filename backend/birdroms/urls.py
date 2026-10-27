from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/roms/", include("apps.roms.urls")),
]

# MEDIA_ROOT is deliberately not served: ROMs are private and only reachable through the
# permission-checked /api/roms/{id}/download/ endpoint.

