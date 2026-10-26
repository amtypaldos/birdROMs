# Completion log — 003 FOSS licensing & project hygiene

**What I implemented:** a root MIT `LICENSE`, plus "Self-hosting / Open source" and "License"
sections in the README. `CONTRIBUTING.md` covers setup with uv and yarn/corepack, how to run
tests, and what a PR needs. I also filled the gaps in the root `.gitignore` and added a comment
for every variable in `backend/.env.example`.

**How I verified it:** `git check-ignore backend/.env` prints the path, and
`git ls-files | grep -E '(^|/)\.env$'` prints nothing. All 12 backend tests pass. `yarn lint`
is clean, all 4 `yarn test` tests pass, and `yarn build` succeeds.

**Follow-up:** the maintainer should confirm MIT over a copyleft license such as AGPL-3.0.
Specs 005, 008 and 010 should add their new env vars to `.env.example`.
