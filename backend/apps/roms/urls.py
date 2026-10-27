from rest_framework.routers import DefaultRouter

from .views import PlaylistViewSet, ROMViewSet

router = DefaultRouter()
router.register("", ROMViewSet, basename="rom")

urlpatterns = router.urls

# Mounted at /api/playlists/ (see birdroms/urls.py).
playlist_router = DefaultRouter()
playlist_router.register("", PlaylistViewSet, basename="playlist")

playlist_urlpatterns = playlist_router.urls
