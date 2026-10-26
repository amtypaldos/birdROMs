# 002 — Frontend tooling

## Decisions
- ESLint 9 flat config (`eslint.config.js`) with `@eslint/js` recommended, `eslint-plugin-react`
  (recommended + jsx-runtime, `prop-types` off) and `eslint-plugin-react-hooks` v5 recommended.
- Vitest pinned to v2 to stay compatible with Vite 5; config lives in the `test` block of
  `vite.config.js` (jsdom env, `src/test/setup.js` registers jest-dom matchers + RTL cleanup).
- `request` in `client.js` is not exported, so the Authorization-header test goes through
  `api.listRoms()` with a stubbed `fetch`. App test mocks `./api/client` via `vi.mock`.

## Notes for later specs
- Frontend uses Yarn 4 PnP (no `.yarnrc.yml`); `.yarn/` and `.pnp.*` are gitignored, so
  `yarn install` is required after clone. ESLint/Vitest work fine under PnP.
- `react-hooks/exhaustive-deps` is a warning; `App.jsx`'s `useEffect` on `loadRoms` doesn't
  currently trip it, but refactors in 011/012 should keep `yarn eslint . --max-warnings 0` clean.
