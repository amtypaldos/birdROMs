from django.contrib import admin
from django.urls import include, path

from apps.accounts.urls import device_urlpatterns
from apps.roms.urls import handheld_urlpatterns, library_urlpatterns, playlist_urlpatterns

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/devices/", include(device_urlpatterns)),
    path("api/roms/", include("apps.roms.urls")),
    path("api/library/", include(library_urlpatterns)),
    path("api/handheld/", include(handheld_urlpatterns)),
    path("api/playlists/", include(playlist_urlpatterns)),
]

# MEDIA_ROOT is deliberately not served: ROMs are private and only reachable through the
# permission-checked /api/roms/{id}/download/ endpoint.

