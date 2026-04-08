from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/roms/", include("apps.roms.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
