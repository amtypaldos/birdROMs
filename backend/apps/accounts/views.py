import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET
from rest_framework import authentication, generics, permissions, status
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.roms.permissions import IsSuperAdmin

from .invites import INVITE_PATH, InviteUnavailable, UsernameTaken, accept_invite, create_invite, find_pending_invite
from .models import Invite
from .serializers import (
    InviteAcceptSerializer,
    InviteCreateSerializer,
    InviteSerializer,
    LoginSerializer,
    MeSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .services import (
    READONLY,
    enabled_methods,
    get_oidc_client,
    local_login_enabled,
    oidc_enabled,
    oidc_login_allowed,
    provision_oidc_user,
    registration_enabled,
    set_role,
)
from .throttles import InviteThrottle, LoginIPThrottle, LoginThrottle, RegisterThrottle

logger = logging.getLogger(__name__)

SESSION_BACKEND = "django.contrib.auth.backends.ModelBackend"

# `oidc_error` codes the redirect to the SPA can carry. The SPA owns the wording (it ignores unknown
# codes), so a crafted link or a hostile `error_description` can never put chosen text on the page.
OIDC_ERRORS = ("provider_error", "failed", "no_subject", "disabled", "not_allowed")


class LocalLoginRequiredMixin:
    """Make the local username/password endpoints 404 unless local login is enabled."""

    def initial(self, request, *args, **kwargs):
        if not local_login_enabled():
            raise Http404("Local login is disabled.")
        super().initial(request, *args, **kwargs)


class CsrfProtectedMixin:
    """Enforce CSRF on unsafe requests to views that don't authenticate by session (login, logout, invite
    sign-up): DRF only checks CSRF for requests it authenticated from a session cookie, which would leave
    login open to login-CSRF."""

    def initial(self, request, *args, **kwargs):
        if request.method not in SAFE_METHODS:
            authentication.SessionAuthentication().enforce_csrf(request)
        super().initial(request, *args, **kwargs)


@require_GET
@ensure_csrf_cookie
def csrf(request):
    """Sets the (script-readable) CSRF cookie; the SPA echoes it in `X-CSRFToken` on unsafe requests."""
    return JsonResponse({"csrfToken": get_token(request)})


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


class RegisterView(LocalLoginRequiredMixin, CsrfProtectedMixin, APIView):
    """Self-registration (only while `registration_enabled()`): creates a read-only account and signs it in."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
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
        login(request._request, user, backend=SESSION_BACKEND)
        return Response({"user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)


class LoginView(LocalLoginRequiredMixin, CsrfProtectedMixin, APIView):
    """Username/password sign-in: starts an HttpOnly session cookie (no token is returned)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle, LoginIPThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request._request,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            return Response(
                {"non_field_errors": ["Unable to log in with provided credentials."]}, status=status.HTTP_400_BAD_REQUEST
            )
        login(request._request, user, backend=SESSION_BACKEND)
        return Response({"user": UserSerializer(user).data})


class LogoutView(CsrfProtectedMixin, APIView):
    """Ends the session (and clears it server-side). Harmless when nobody is signed in."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)


class InviteListCreateView(LocalLoginRequiredMixin, generics.ListCreateAPIView):
    """Admin: list invites (pending, used, expired, revoked) or create one.

    The create response is the only time the token (and so the link) is ever shown.
    """

    permission_classes = [IsSuperAdmin]
    authentication_classes = [authentication.SessionAuthentication]
    serializer_class = InviteSerializer
    queryset = Invite.objects.select_related("used_by", "created_by")
    pagination_class = None

    def create(self, request, *args, **kwargs):
        serializer = InviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        invite, raw = create_invite(
            created_by=request.user, role=data["role"], ttl_days=data.get("expires_in_days"), label=data["label"]
        )
        path = INVITE_PATH.format(token=raw)
        body = {**InviteSerializer(invite).data, "token": raw, "path": path, "url": request.build_absolute_uri(path)}
        return Response(body, status=status.HTTP_201_CREATED, headers={"Cache-Control": "no-store"})


class InviteRevokeView(LocalLoginRequiredMixin, APIView):
    """Admin: revoke a pending invite (a used one is history and stays as it is)."""

    permission_classes = [IsSuperAdmin]
    authentication_classes = [authentication.SessionAuthentication]

    def delete(self, request, pk):
        with transaction.atomic():
            invite = Invite.objects.select_for_update().filter(pk=pk).first()
            if invite is None:
                raise Http404("No such invite.")
            if invite.status() == "used":
                return Response({"detail": "This invite was already used."}, status=status.HTTP_409_CONFLICT)
            if invite.revoked_at is None and invite.status() == "pending":
                invite.revoked_at = timezone.now()
                invite.save(update_fields=["revoked_at"])
        return Response(InviteSerializer(invite).data)


INVITE_UNAVAILABLE = {"detail": "This invite link is invalid, expired or already used."}


class InviteCheckView(LocalLoginRequiredMixin, CsrfProtectedMixin, APIView):
    """Public: is this token a usable invite? (POST so the token never lands in a URL or access log.)"""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [InviteThrottle]

    def post(self, request):
        if find_pending_invite(request.data.get("token") if hasattr(request.data, "get") else None) is None:
            return Response(INVITE_UNAVAILABLE, status=status.HTTP_404_NOT_FOUND)
        return Response({"valid": True})


class InviteAcceptView(LocalLoginRequiredMixin, CsrfProtectedMixin, APIView):
    """Public: redeem an invite by choosing a username and password. Creates the account and signs it in."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [InviteThrottle, LoginIPThrottle]

    def post(self, request):
        serializer = InviteAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            user = accept_invite(data["token"], data["username"], data["password"], data["email"])
        except InviteUnavailable:
            return Response(INVITE_UNAVAILABLE, status=status.HTTP_404_NOT_FOUND)
        except UsernameTaken:
            return Response({"username": ["That username is already taken."]}, status=status.HTTP_400_BAD_REQUEST)
        login(request._request, user, backend=SESSION_BACKEND)
        return Response({"user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)


def _redirect_to_spa(error=None):
    """Send the browser back to the web UI. A success carries nothing at all: the session cookie set on
    this response is the sign-in. A failure carries one of the fixed `OIDC_ERRORS` codes."""
    url = settings.OIDC["LOGIN_REDIRECT_URL"]
    if error:
        url = f"{url}#{urlencode({'oidc_error': error})}"
    return HttpResponseRedirect(url)


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
        # The provider's text is untrusted (and could be crafted into a link): log it, show a fixed message.
        logger.warning(
            "OIDC provider returned an error: %s (%s)", request.GET.get("error"), request.GET.get("error_description", "")
        )
        return _redirect_to_spa("provider_error")

    client = get_oidc_client()
    try:
        # Validates state + nonce, exchanges the code, and verifies the ID token signature/claims.
        token = client.authorize_access_token(request)
        claims = dict(token.get("userinfo") or {})
        if settings.OIDC["GROUPS_CLAIM"] not in claims:
            claims = {**dict(client.userinfo(token=token)), **claims}
    except Exception:  # authlib raises several error types (state mismatch, OAuthError, JOSE errors)
        logger.warning("OIDC callback failed", exc_info=True)
        return _redirect_to_spa("failed")

    if not claims.get("sub"):
        return _redirect_to_spa("no_subject")

    # Before any account is created or touched: with an allow-list configured, only matching users get in.
    if not oidc_login_allowed(claims):
        logger.warning("OIDC login refused by the allow-list for subject %s", claims["sub"])
        return _redirect_to_spa("not_allowed")

    user = provision_oidc_user(claims)
    if not user.is_active:
        return _redirect_to_spa("disabled")
    login(request, user, backend=SESSION_BACKEND)
    return _redirect_to_spa()
