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


class RegisterThrottle(SimpleRateThrottle):
    """Limit account creation per client address.

    Behind a reverse proxy this is only as accurate as DRF's `NUM_PROXIES` setting.
    """

    scope = "register"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
