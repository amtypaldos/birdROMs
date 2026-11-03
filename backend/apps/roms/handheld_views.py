"""Handheld app info + download for signed-in users (any role, including device tokens).

The download is the published package with this server's address added, so the app knows where to pair."""

from django.http import FileResponse
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .handheld import handheld_info, handheld_path, personalized_package


class BinaryRenderer(BaseRenderer):
    """Accept any Accept header. The download returns a zip, not JSON."""

    media_type = "*/*"
    format = "binary"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


def request_platform(request):
    platform = request.query_params.get("platform", "muos")
    if platform not in {"muos", "switch"}:
        raise ValidationError({"platform": "Choose muos or switch."})
    return platform


class HandheldInfoView(APIView):
    def get(self, request):
        platform = request_platform(request)
        absent = {"available": False, "platform": "switch"} if platform == "switch" else {"available": False}
        return Response(handheld_info(platform=platform) or absent)


class HandheldDownloadView(APIView):
    renderer_classes = [BinaryRenderer]

    def get(self, request):
        platform = request_platform(request)
        path = handheld_path(platform=platform)
        if not path.is_file():
            raise NotFound("The handheld app has not been published yet.")
        return FileResponse(personalized_package(request.build_absolute_uri("/"), platform=platform), as_attachment=True, filename="birdROMs-switch.zip" if platform == "switch" else path.name)
