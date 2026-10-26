# 012 — Retro / arcade dark redesign

## Decisions
- **All design values are CSS custom properties** in `:root` (`--color-*`, `--family-*`, `--font-*`,
  `--space-*`, `--radius-*`). Components only use tokens.
- **Fonts are bundled** with `@fontsource/press-start-2p` (display: logo, section headings, placeholder
  initials) and `@fontsource/chakra-petch` (body). Loading from Google Fonts would leak visitors' IPs
  from a private, self-hosted app, so the fonts ship in the build.
- **Platform family accent**: `platformFamily()` (exported from `App.jsx`) maps platform names to
  `nintendo|sega|sony|atari|other`. The card's `data-family` sets `--accent`, which drives the badge,
  hover glow and placeholder colors. New platforms fall back to cyan, so nothing breaks.
- **The placeholder art is decorative** (`aria-hidden`). The title is already an `<h3>` on the card, and
  the existing test requires that no `img` role is exposed for ROMs without art. Real covers keep
  `alt={title}`.
- **Loading state**: `loading` starts true when authed, so "No ROMs found." never flashes before the
  first response. Skeleton cards appear only when there are no results yet. Refreshes keep the current
  grid in place.
- Upload now catches errors (shown inline) and disables itself while busy or when no file is selected.
  It also clears the native file input after success.
- Role text stays the raw `super_admin`/`readonly` string in the DOM, uppercased only by CSS, so the
  tests and screen readers see the real value.

## Contrast
Ratios were computed with a script for every text/background pair: dim text ≥7:1, the family badges
are 5.9–10.7:1, admin magenta is 6.1:1, and dark-on-cyan/lime buttons are ≥14:1. All pass WCAG AA.

## Issues
- jsdom lacks `URL.revokeObjectURL`. Tests that render covers and then unmount must stub `URL`.
- Headless Chrome won't go below a ~500px window width. For true phone-width screenshots, render the
  page in a fixed-width iframe.
- The `frontend-design` skill named in the constitution isn't installed in this environment, so the
  visual direction was set by hand against the spec.
