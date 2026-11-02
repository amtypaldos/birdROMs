# Self-hosted Switch distribution complete

Implemented and independently reviewed backend package APIs/validation, dual
container bundles and a clearer platform-specific Handheld page. Companion
Switch client stages and installs authenticated server updates while preserving
writable config/token/ROM settings.

Evidence: 615 Django tests, 161 frontend tests, lint/build, native host/package
tests, clean NRO build, successful release pipelines, image-based browser/native
smoke tests, and healthy pinned production deployment at 2026.11.02.

Follow-up: user physical Switch update/restart/power-loss checklist. Existing
PWA registration warning reproduced against baseline and left unchanged.
