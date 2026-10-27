from django.core.exceptions import ImproperlyConfigured

from .auth_config import _parse_bool

# Placeholder secret keys that must never be used with DEBUG off.
UNSAFE_SECRET_KEYS = frozenset({"", "unsafe-dev-secret-key", "change-me"})


def parse_csv(env, name) -> list:
    """A comma-separated env var as a list, ignoring blanks."""
    return [item.strip() for item in env.get(name, "").split(",") if item.strip()]


def parse_debug(env) -> bool:
    """`DJANGO_DEBUG`, failing closed: debug mode is on only when explicitly set to `true`.

    An unset or mistyped value must never leave a production instance serving debug pages.
    """
    return env.get("DJANGO_DEBUG", "").strip().lower() == "true"


def check_secret_key(secret_key: str, debug: bool) -> None:
    """Refuse to start in production with a missing or placeholder `DJANGO_SECRET_KEY`."""
    if not debug and secret_key.strip() in UNSAFE_SECRET_KEYS:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set to a long random value when DJANGO_DEBUG is False."
        )


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
