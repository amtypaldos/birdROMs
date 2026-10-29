import logging
from urllib.parse import urlencode

from django.conf import settings
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_GET
from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import MeSerializer, RegisterSerializer, UserSerializer
from .throttles import LoginThrottle, RegisterThrottle
from .services import (
    READONLY,
    enabled_methods,
    get_oidc_client,
    local_login_enabled,
    oidc_enabled,
    provision_oidc_user,
    registration_enabled,
    set_role,
)

logger = logging.getLogger(__name__)


class LocalLoginRequiredMixin:
    """Make the local username/password endpoints 404 unless local login is enabled."""

    def initial(self, request, *args, **kwargs):
        if not local_login_enabled():
            raise Http404("Local login is disabled.")
        super().initial(request, *args, **kwargs)


class AuthConfigView(APIView):
    """Public: which login methods the SPA should offer."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        methods = enabled_methods()
        data = {"methods": methods, "registration": registration_enabled()}
        if "oidc" in methods:
            data["oidc"] = {"provider_name": settings.OIDC["PROVIDER_NAME"], "login_url": reverse("oidc-login")}
        return Response(data)


class RegisterView(LocalLoginRequiredMixin, APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RegisterThrottle]

    def initial(self, request, *args, **kwargs):
        # 404 (not 403) so a closed server doesn't advertise the endpoint; checked before throttling.
        if not registration_enabled():
            raise Http404("Registration is closed.")
        super().initial(request, *args, **kwargs)

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        set_role(user, READONLY)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)


class LoginView(LocalLoginRequiredMixin, ObtainAuthToken):
    throttle_classes = [LoginThrottle]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        token = Token.objects.get(key=response.data["token"])
        return Response({"token": token.key, "user": UserSerializer(token.user).data}, status=status.HTTP_200_OK)


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)


def _redirect_to_spa(**fragment):
    # The token travels in the URL fragment, which browsers never send to servers or proxies.
    return HttpResponseRedirect(f"{settings.OIDC['LOGIN_REDIRECT_URL']}#{urlencode(fragment)}")


@require_GET
def oidc_login(request):
    if not oidc_enabled():
        raise Http404("OIDC login is disabled.")
    return get_oidc_client().authorize_redirect(request, settings.OIDC["REDIRECT_URI"])


@require_GET
def oidc_callback(request):
    if not oidc_enabled():
        raise Http404("OIDC login is disabled.")
    if request.GET.get("error"):
        return _redirect_to_spa(oidc_error=request.GET.get("error_description") or request.GET["error"])

    client = get_oidc_client()
    try:
        # Validates state + nonce, exchanges the code, and verifies the ID token signature/claims.
        token = client.authorize_access_token(request)
        claims = dict(token.get("userinfo") or {})
        if settings.OIDC["GROUPS_CLAIM"] not in claims:
            claims = {**dict(client.userinfo(token=token)), **claims}
    except Exception:  # authlib raises several error types (state mismatch, OAuthError, JOSE errors)
        logger.warning("OIDC callback failed", exc_info=True)
        return _redirect_to_spa(oidc_error="Single sign-on failed. Please try again.")

    if not claims.get("sub"):
        return _redirect_to_spa(oidc_error="The identity provider did not return a subject.")

    user = provision_oidc_user(claims)
    if not user.is_active:
        return _redirect_to_spa(oidc_error="This account is disabled.")
    api_token, _ = Token.objects.get_or_create(user=user)
    return _redirect_to_spa(oidc_token=api_token.key)
