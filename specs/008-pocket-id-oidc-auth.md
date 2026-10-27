# 008 — Configurable authentication (local + OIDC/SSO, Pocket ID reference)

## Status: COMPLETE
Priority: 8

## Problem / Context
Auth should be **configurable**: a self-hoster chooses which login methods are enabled —
**local** username/password and/or **OIDC/SSO**. Pocket ID is the reference OIDC provider, but
because it speaks standard OIDC, the same code path serves any OIDC/SSO provider (Authentik,
Keycloak, Authelia, Google, …). Today auth is local-only with a register form; this spec makes
the method set env-driven. (SAML is explicitly out of scope — OIDC covers the SSO ask.)

## Acceptance Criteria
- An `AUTH_METHODS` env var (e.g. `local,oidc`) enables any subset of methods; order is not
  significant. The frontend only renders controls for enabled methods (queried via a small
  public config endpoint, e.g. `GET /api/auth/config/`).
- **Local method**: existing username/password `login` (and `register`) endpoints work when
  `local` is enabled. They are also force-enabled when `ALLOW_LOCAL_LOGIN` is true (defaults to
  the value of `DEBUG`) so local dev always works. When disabled, the endpoints return 404/403.
- **OIDC/SSO method**: standard Authorization Code login using a maintained library
  (e.g. `authlib` or `mozilla-django-oidc` — document the choice). A single provider is
  configured by env: issuer/discovery URL, client ID, client secret, redirect URI, and scopes.
  Pocket ID is the documented example; the README shows config for at least one other provider.
- First OIDC login provisions a Django user and maps a role group: default `readonly`,
  `super_admin` from a configurable claim/group (`OIDC_ADMIN_GROUP`). Returning users match on a
  stable subject/email. No secrets in the repo.
- After any successful login the backend hands the SPA an API credential compatible with the
  existing DRF auth (reuse the token flow) so the rest of the API is unchanged.
- `GET /api/auth/me/` returns the current user's `id`, `username`, `email`, and `role`.
- Frontend: shows a local login/register form and/or a "Login with SSO" button depending on
  which methods are enabled; handles the OIDC redirect + callback and stores the token.
- At least these configurations behave correctly: local-only, OIDC-only, and both enabled.

## Completion Signal
Implementation:
- [x] `AUTH_METHODS` gating + `GET /api/auth/config/` reporting enabled methods.
- [x] Local login/register honoring `AUTH_METHODS` and `ALLOW_LOCAL_LOGIN`.
- [x] Generic OIDC login + callback + user provisioning + role mapping (env-configured).
- [x] `GET /api/auth/me/` returning user + role.
- [x] Frontend renders only enabled methods; OIDC + local both wired.

Testing:
- [x] Backend tests (mocking the OIDC provider — no live SSO): OIDC role mapping; `/me`;
      local endpoints enabled/disabled per `AUTH_METHODS`/`ALLOW_LOCAL_LOGIN`; `/auth/config/`
      reflects the enabled set.
- [x] `uv run python manage.py test`, `yarn test`, `yarn lint`, `yarn build` pass.

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 1 -->
