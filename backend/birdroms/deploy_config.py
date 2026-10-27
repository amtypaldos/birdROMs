from django.core.exceptions import ImproperlyConfigured

from .auth_config import _parse_bool

# Placeholder secret keys that must never be used with DEBUG off.
UNSAFE_SECRET_KEYS = frozenset({"", "unsafe-dev-secret-key", "change-me"})


def parse_csv(env, name) -> list:
    """A comma-separated env var as a list, ignoring blanks."""
    return [item.strip() for item in env.get(name, "").split(",") if item.strip()]


def parse_debug(env) -> bool:
    """`DJANGO_DEBUG`, failing closed: debug mode is on only when set to the literal `True`
    (case-insensitive). `1`, `yes`, `on` and anything else mean off.

    An unset or mistyped value must never leave a production instance serving debug pages.
    """
    return env.get("DJANGO_DEBUG", "").strip().lower() == "true"


def check_secret_key(secret_key: str, debug: bool) -> None:
    """Refuse to start in production with a missing or placeholder `DJANGO_SECRET_KEY`."""
    if not debug and secret_key.strip() in UNSAFE_SECRET_KEYS:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set to a long random value unless DJANGO_DEBUG is exactly "
            "'True' (any other value, or leaving it unset, counts as debug off)."
        )


def parse_num_proxies(env) -> int:
    """`NUM_PROXIES`: how many reverse proxies sit in front of Django, for DRF's client address.

    DRF takes the client address from the Nth-from-last `X-Forwarded-For` entry, so a client
    cannot pick its own by sending that header. The default of 1 matches the production stack,
    where the `web` nginx container is the only proxy; add one for each extra proxy in front of
    it (a TLS terminator makes it 2). 0 ignores `X-Forwarded-For` and uses the socket address.
    """
    raw = env.get("NUM_PROXIES", "").strip()
    if not raw:
        return 1
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        raise ImproperlyConfigured(f"NUM_PROXIES must be a non-negative integer, got {raw!r}.")
    return value


def parse_proxy_settings(env) -> dict:
    """Settings for running behind a TLS-terminating reverse proxy.

    `DJANGO_BEHIND_HTTPS_PROXY=True` trusts the proxy's `X-Forwarded-Proto` header so Django
    knows requests are HTTPS, and marks session/CSRF cookies Secure.
    """
    raw = env.get("DJANGO_BEHIND_HTTPS_PROXY", "").strip()
    behind_https = _parse_bool("DJANGO_BEHIND_HTTPS_PROXY", raw) if raw else False
    return {
        "CSRF_TRUSTED_ORIGINS": parse_csv(env, "DJANGO_CSRF_TRUSTED_ORIGINS"),
        "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https") if behind_https else None,
        "SESSION_COOKIE_SECURE": behind_https,
        "CSRF_COOKIE_SECURE": behind_https,
    }
