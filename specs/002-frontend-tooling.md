# 002 — Frontend tooling: lint + test runner

## Status: COMPLETE
Priority: 2

## Problem / Context
The frontend (`frontend/`) has **no linter and no test runner** — `package.json` only has
`dev`/`build`/`preview`. The constitution expects `yarn lint` and `yarn test` to exist so
later frontend specs can be verified. This spec adds that tooling without changing app behavior.

## Acceptance Criteria
- ESLint is configured for React + hooks (flat config or `.eslintrc`), with a `yarn lint`
  script. `yarn lint` passes on the current `src/`.
- Vitest + React Testing Library + jsdom are added as devDependencies, with a `yarn test`
  script that runs once and exits (CI-friendly, e.g. `vitest run`).
- At least these tests exist and pass:
  - `src/api/client.js`: `getToken`/`setToken` round-trip via a mocked `localStorage`, and
    `request` attaches the `Authorization: Token …` header when a token is set.
  - `src/App.jsx`: renders the login form when there is no token (smoke render with mocked api).
- Yarn/corepack workflow from the README still works; `yarn build` still succeeds.

## Completion Signal
Implementation:
- [x] ESLint config + `lint` script added; `yarn lint` clean.
- [x] Vitest + Testing Library + jsdom added; `test` script added.
- [x] client.js and App.jsx tests written.

Testing:
- [x] `yarn lint` exits 0.
- [x] `yarn test` (run mode) exits 0 with the new tests passing.
- [x] `yarn build` still succeeds.

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 1 -->
