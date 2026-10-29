from django.http import HttpResponse
from rest_framework.throttling import SimpleRateThrottle


class LoginThrottle(SimpleRateThrottle):
    """Limit password guesses per submitted username.

    Keyed on the username rather than the client address: behind a proxy the address is either
    the proxy's or a spoofable `X-Forwarded-For`, so an address-keyed limit could be dodged.
    The trade-off is that someone can briefly lock a known username out of local login.
    """

    scope = "login"

    def get_cache_key(self, request, view):
        username = request.data.get("username") if hasattr(request.data, "get") else None
        username = str(username or "").strip().lower()
        if not username:
            return None  # Nothing to guess against; the serializer rejects the request.
        return self.cache_format % {"scope": self.scope, "ident": username}


class LoginIPThrottle(SimpleRateThrottle):
    """Limit login attempts per client address, to slow password spraying across many usernames.

    Behind a reverse proxy this is only as accurate as DRF's `NUM_PROXIES` setting.
    """

    scope = "login_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class AdminLoginThrottle(SimpleRateThrottle):
    """Limit submissions to the Django admin login form per submitted username.

    Used by `AdminLoginThrottleMiddleware`, because the admin's own login view is not a DRF view.
    """

    scope = "admin_login"

    def get_cache_key(self, request, view):
        username = str(request.POST.get("username") or "").strip().lower()
        if not username:
            return None
        return self.cache_format % {"scope": self.scope, "ident": username}


class AdminLoginThrottleMiddleware:
    """Throttle POST /admin/login/ per username. The admin login view is Django's, not DRF's."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path.rstrip("/") or "/"
        if request.method == "POST" and path == "/admin/login":
            throttle = AdminLoginThrottle()
            if not throttle.allow_request(request, None):
                return HttpResponse("Too many login attempts. Try again shortly.", status=429)
        return self.get_response(request)


class RegisterThrottle(SimpleRateThrottle):
    """Limit account creation per client address.

    Behind a reverse proxy this is only as accurate as DRF's `NUM_PROXIES` setting.
    """

    scope = "register"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class InviteThrottle(SimpleRateThrottle):
    """Limit invite lookups and sign-ups per client address."""

    scope = "invite"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class PairStartThrottle(SimpleRateThrottle):
    """Limit unauthenticated creation of pairing requests per client address."""

    scope = "pair_start"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class PairCodeThrottle(SimpleRateThrottle):
    """Limit approve/poll attempts per client address, so short codes can't be brute-forced.

    Sized to allow a device polling every couple of seconds for the life of a pairing code.
    """

    scope = "pair_code"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
