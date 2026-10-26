# 011 — Role-aware frontend

## Status: COMPLETE
Priority: 11

## Problem / Context
The frontend shows Upload and Scrape controls to **every** authenticated user, so a `readonly`
user sees an Upload panel that just 403s, and the UI never shows who is logged in. With auth now
via Pocket ID + `/api/auth/me/` (spec 008), the UI should be role-aware.

> Approach: use the `frontend-design` skill for any visual additions so they fit the app's
> emerging look (the full retro/arcade restyle lands in spec 012).

## Acceptance Criteria
- After login the UI shows the current username and role (from `/api/auth/me/`), plus a working
  Logout.
- Upload and Scrape-cover controls are **hidden** for users whose role is not `super_admin`;
  `readonly` users see only the library + download.
- Works for both Pocket ID login and the dev local-login path.
- No dead UI: controls the user cannot use are not rendered (not merely disabled).
- Covered by a frontend test (spec 002).

## Completion Signal
Implementation:
- [x] Current user + role displayed; Logout works.
- [x] Write controls gated on `super_admin`.

Testing:
- [x] Frontend test: readonly user does not see Upload; super_admin does.
- [x] `yarn test`, `yarn lint`, `yarn build` pass.

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 1 -->
