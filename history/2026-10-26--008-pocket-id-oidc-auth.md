# 008 — Configurable authentication (local + OIDC)

## Decisions
- **Authlib** (`authlib.integrations.django_client`) over mozilla-django-oidc. It is
  provider-agnostic, handles discovery, state/nonce and PKCE (S256), and verifies the ID token
  against the JWKS. The client is built lazily and cached per config, so `override_settings` works
  in tests and import does no network I/O.
- **Settings parsing** lives in `birdroms/auth_config.py`, the same pattern as `uploads.py`.
  Unknown methods, bad booleans, and `oidc` without issuer/client id/secret/redirect URI fail fast
  with `ImproperlyConfigured`. The views read `settings.AUTH_METHODS` / `ALLOW_LOCAL_LOGIN` per
  request.
- **`OIDC_REDIRECT_URI` is required**, not derived from `build_absolute_uri`. The Vite dev proxy
  (`changeOrigin`) and reverse proxies change Host, so a derived URI would not match the one
  registered at the provider.
- **Token hand-off via URL fragment** (`#oidc_token=`). Fragments are never sent to servers or
  proxies, and the SPA strips the token with `history.replaceState` before the first render.
  Errors arrive as `#oidc_error=` with generic text. Details are logged server-side only.
- **Identity = `(iss, sub)`** in the new `OIDCIdentity` model, never the username. A username
  collision with a local account gets a `-2` suffix rather than being taken over. Linking by email
  is opt-in (`OIDC_LINK_BY_EMAIL`) and requires `email_verified is True`.
- **The role is re-synced on every SSO login** from `OIDC_GROUPS_CLAIM`, so revoking admin at the
  IdP takes effect. Django superusers are exempt. If the groups claim is missing from the ID
  token, the userinfo endpoint is queried.
- Disabled methods return **404** (local endpoints via a mixin on `initial`, OIDC views directly).
- Test settings pin `AUTH_METHODS={"local"}` and `ALLOW_LOCAL_LOGIN=False`, so the suite does
  not depend on a developer's `.env`.

## Notes for later specs
- 011 (role-aware UI): `api.me()` already gives `role`, and App keeps it in `me` state.
- 012 (redesign): the auth panel uses the new `a.button` and `.muted` styles.
- 013 (deployment): set `OIDC_REDIRECT_URI` / `OIDC_LOGIN_REDIRECT_URL` to the public URL. The
  session cookie (state/nonce) must survive the provider round-trip, so keep SameSite=Lax.
- 014 (CI): the backend tests mock the provider and need no network.
