# 012 — Retro / arcade dark visual redesign

## Status: COMPLETE
Priority: 12

## Problem / Context
The UI is functional but plain (a single stacked `App.jsx` with minimal `styles.css`). Now that
the functional pieces exist (auth, library, search/filter, role gating, cover art), give it a
cohesive, distinctive **retro/arcade dark** look that makes the cover art the star.

> Approach: use the `frontend-design` skill to drive the visual direction — intentional
> typography, color, and layout, not a templated default.

## Acceptance Criteria
- A cohesive dark theme with tasteful neon/CRT accents — intentional, not a templated default.
  Apply deliberate typography, spacing, and color (define colors as reusable tokens).
- The library becomes a **cover-art-forward responsive grid** of ROM cards: box art, title, and
  a platform badge; graceful placeholder art when a ROM has none.
- Login, upload, search/filter, and the role display all share the theme. Hover/focus, loading,
  empty, and error states are all styled.
- Responsive from phone to desktop with no horizontal scroll; accessible contrast (WCAG AA) even
  with the dark/neon palette; keyboard-focusable controls keep visible focus.
- No functional regressions.

## Completion Signal
Implementation:
- [x] Retro/arcade dark theme with tokenized colors + typography.
- [x] Cover-art grid of ROM cards with platform badges + placeholders.
- [x] Themed login/upload/search/role views; loading/empty/error states.
- [x] Responsive + AA contrast + visible focus.

Testing:
- [x] `yarn lint`, `yarn test`, `yarn build` pass; a render/smoke test covers the grid.
- [x] Manual check at mobile + desktop widths (note results in the completion log).

Commit and push. Output `<promise>DONE</promise>` only when all boxes are verified.

<!-- NR_OF_TRIES: 1 -->
