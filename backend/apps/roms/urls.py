from rest_framework.routers import DefaultRouter

from .views import ROMViewSet

router = DefaultRouter()
router.register("", ROMViewSet, basename="rom")

urlpatterns = router.urls
