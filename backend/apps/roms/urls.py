from django.urls import path
from rest_framework.routers import DefaultRouter

from .handheld_views import HandheldDownloadView, HandheldInfoView
from .library_views import LibraryScanView, LibraryStatusView
from .views import PlaylistViewSet, ROMViewSet

router = DefaultRouter()
router.register("", ROMViewSet, basename="rom")

urlpatterns = router.urls

# Mounted at /api/playlists/ (see birdroms/urls.py).
playlist_router = DefaultRouter()
playlist_router.register("", PlaylistViewSet, basename="playlist")

playlist_urlpatterns = playlist_router.urls

# Mounted at /api/library/ (see birdroms/urls.py).
library_urlpatterns = [
    path("status/", LibraryStatusView.as_view(), name="library-status"),
    path("scan/", LibraryScanView.as_view(), name="library-scan"),
]

# Mounted at /api/handheld/ (see birdroms/urls.py).
handheld_urlpatterns = [
    path("", HandheldInfoView.as_view(), name="handheld-info"),
    path("download/", HandheldDownloadView.as_view(), name="handheld-download"),
]
