# Security policy

## Reporting a vulnerability

Please report security problems privately, not in a public issue. Use this repository's
**Security** tab, then **Report a vulnerability** (a private GitHub security advisory). Include what
you found, how to reproduce it, the version or commit, and your deployment type (Docker, auth methods,
storage backend) if it matters.

You can expect an acknowledgement within a few days. This is a volunteer project, so fixes happen on a
best-effort basis; please give us reasonable time to ship one before you disclose publicly.

## Scope

birdROMs is built for a small, trusted group sharing a private library. In scope: authentication and
roles (local login, OIDC, device pairing and tokens), access to ROMs and cover art (downloads must always
be permission-checked), upload handling (file type, size, path safety), the cover-art scrapers (SSRF),
and the Docker images and compose files.

Known, documented limitations are listed in
[docs/superpowers/reports/2026-10-26-security-audit.md](docs/superpowers/reports/2026-10-26-security-audit.md)
(some of which predate the move to cookie sessions, so check it against the current code). Web sign-in is an
HttpOnly session cookie protected by CSRF tokens; handheld device tokens are separate, read-only and expire
after `DEVICE_TOKEN_IDLE_DAYS` of disuse. Self-registration is closed by default; if you open it with
`ALLOW_REGISTRATION` or the Django admin setting, anyone who can reach the site can create a read-only
account, so do not do that on an internet-facing instance unless that is what you want). Invite links
are single-use, expire (`INVITE_TTL_DAYS`) and are stored only as a SHA-256 digest; treat a link like a
password until it is used. To restrict SSO, set `OIDC_ALLOWED_GROUPS` or `OIDC_ALLOWED_EMAIL_DOMAINS`.
Hardening advice is in [SELF_HOSTING.md](SELF_HOSTING.md).

## Supported versions

Only the latest release (and `main`) receives fixes.

## Please do not

Publish or share ROMs, BIOS files or other copyrighted material in reports; use a description or a
synthetic file instead.
