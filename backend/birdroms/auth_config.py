from django.core.exceptions import ImproperlyConfigured

KNOWN_AUTH_METHODS = ("local", "oidc")
DEFAULT_OIDC_SCOPES = "openid email profile groups"

# Env vars that must be set when the `oidc` method is enabled.
REQUIRED_OIDC_VARS = ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI")


def _parse_bool(name, raw):
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ImproperlyConfigured(f"{name} must be true or false, got {raw!r}.")


def parse_auth_methods(env) -> frozenset:
    """Read the comma-separated `AUTH_METHODS` (default `local`); order is not significant."""
    raw = env.get("AUTH_METHODS", "").strip() or "local"
    methods = frozenset(m.strip().lower() for m in raw.split(",") if m.strip())
    unknown = methods - set(KNOWN_AUTH_METHODS)
    if unknown:
        raise ImproperlyConfigured(
            f"AUTH_METHODS has unknown method(s) {sorted(unknown)}; choose from {list(KNOWN_AUTH_METHODS)}."
        )
    return methods


def parse_allow_local_login(env, debug: bool) -> bool:
    """`ALLOW_LOCAL_LOGIN` force-enables local login; it defaults to the value of DEBUG."""
    raw = env.get("ALLOW_LOCAL_LOGIN", "").strip()
    return debug if not raw else _parse_bool("ALLOW_LOCAL_LOGIN", raw)


def parse_oidc_settings(env, methods) -> dict:
    """Collect the OIDC provider config, failing fast if `oidc` is enabled but incomplete."""
    if "oidc" in methods:
        missing = [name for name in REQUIRED_OIDC_VARS if not env.get(name, "").strip()]
        if missing:
            raise ImproperlyConfigured(f"AUTH_METHODS includes oidc but these settings are missing: {', '.join(missing)}.")
    issuer = env.get("OIDC_ISSUER", "").strip().rstrip("/")
    discovery_url = env.get("OIDC_DISCOVERY_URL", "").strip()
    if issuer and not discovery_url:
        discovery_url = f"{issuer}/.well-known/openid-configuration"
    return {
        "ISSUER": issuer,
        "DISCOVERY_URL": discovery_url,
        "CLIENT_ID": env.get("OIDC_CLIENT_ID", "").strip(),
        "CLIENT_SECRET": env.get("OIDC_CLIENT_SECRET", "").strip(),
        "REDIRECT_URI": env.get("OIDC_REDIRECT_URI", "").strip(),
        "SCOPES": env.get("OIDC_SCOPES", "").strip() or DEFAULT_OIDC_SCOPES,
        "GROUPS_CLAIM": env.get("OIDC_GROUPS_CLAIM", "").strip() or "groups",
        "ADMIN_GROUP": env.get("OIDC_ADMIN_GROUP", "").strip(),
        "LOGIN_REDIRECT_URL": env.get("OIDC_LOGIN_REDIRECT_URL", "").strip() or "/",
        "PROVIDER_NAME": env.get("OIDC_PROVIDER_NAME", "").strip() or "SSO",
        "LINK_BY_EMAIL": _parse_bool("OIDC_LINK_BY_EMAIL", env.get("OIDC_LINK_BY_EMAIL", "") or "false"),
    }
