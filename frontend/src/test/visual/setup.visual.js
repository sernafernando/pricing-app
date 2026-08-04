/**
 * Setup for the `visual` project (real Chromium via Playwright).
 *
 * DELIBERATELY NOT `src/test/setup.js`. That file exists to make jsdom survive:
 * it stubs `localStorage`, `matchMedia` and `scrollIntoView` because jsdom does
 * not implement them, and it mocks modules with paths relative to itself. A real
 * browser implements all of those, and re-stubbing them here would mean these
 * tests no longer describe the browser the users actually run.
 *
 * WHAT THIS FILE IS FOR
 * Reproducing the app's GLOBAL CSS CASCADE exactly. Every assertion in this
 * project reads a computed value, and a computed value is a function of the
 * whole cascade, not of one file. Import less than the app does and you measure
 * a rig that does not exist in production; import it in a different order and
 * you measure a different cascade. So the order below is copied from the app:
 *
 *   main.jsx : index.css                      (Tailwind preflight — this is
 *                                              where `box-sizing: border-box`
 *                                              comes from; nothing else sets it)
 *   App.jsx  : design-tokens.css              (`:root` + `[data-theme]` tokens)
 *              components.css
 *              buttons-tesla.css
 *              modals-tesla.css
 *              table-tesla.css
 *              theme.css
 *
 * `forms-tesla.css` is intentionally absent: it is never imported globally, it
 * is only ever reached through `composes:`. Importing it here would create a
 * global `.input` that does not exist in the app and would silently mask a
 * broken compose chain — the exact failure this suite is meant to detect.
 */

import '../../index.css';
import '../../styles/design-tokens.css';
import '../../styles/components.css';
import '../../styles/buttons-tesla.css';
import '../../styles/modals-tesla.css';
import '../../styles/table-tesla.css';
import '../../styles/theme.css';

import { afterEach } from 'vitest';
import { cleanup } from 'vitest-browser-react';

/**
 * Freeze all transitions and animations.
 *
 * NOT cosmetic, and NOT hiding anything. `theme.css` ships a global
 *
 *     * { transition: background-color .3s, color .3s, border-color .3s }
 *
 * on EVERY element, and `forms-tesla.css` transitions `box-shadow` for 200ms.
 * Those are precisely the properties a theme switch and a focus event change,
 * so `getComputedStyle()` called right after either one returns an INTERPOLATED
 * value — the animation's starting frame, i.e. the old colour and a
 * `rgba(0,0,0,0) 0 0 0 0` box-shadow. Assertions written against that are
 * timing-dependent and would be flaky rather than wrong.
 *
 * Killing the transitions makes every read the settled value. The transitions
 * themselves are not under test; the values they settle on are.
 *
 * Injected as the LAST stylesheet with `!important` so it outranks the app's
 * own `*` rule regardless of source order.
 */
const freeze = document.createElement('style');
freeze.textContent = `
  *, *::before, *::after {
    transition: none !important;
    animation: none !important;
  }
`;
document.head.append(freeze);

/**
 * FONTS ARE DELIBERATELY *NOT* PINNED HERE — and that bounds what this suite
 * can honestly claim.
 *
 * The app loads Inter from the Google Fonts CDN in `index.html`. Browser mode
 * serves its own page and never runs `index.html`, so nothing loads it, and
 * `font-family: 'Inter', system-ui, …` resolves against whatever the machine
 * has. Measured, for the longest PxQ label at 12px/500:
 *
 *   this machine (Inter installed system-wide)   117.33px
 *   ubuntu-latest (no Inter -> system-ui)        129.42px
 *   repo's own public/fonts/Inter-Regular.ttf    146.00px
 *
 * Pinning to the repo's TTF was tried and REJECTED: that file is a 67 KB subset
 * cut for pdfme's PDF generation, not a web font. Characters outside the subset
 * (the "í" in "envío") fall back mid-string, so it measures wider than real
 * Inter and is the least representative of the three.
 *
 * Consequence, stated plainly: every metric this suite asserts is
 * font-INDEPENDENT except one — whether the longest label fits on a single
 * line. `.label` sets `line-height: var(--leading-tight)`, so a line is always
 * 12 x 1.25 = 15px regardless of typeface; only the 1-line-vs-2 decision moves.
 * Both realistic values (117px here, 129px on CI) fit inside the 144px field,
 * so the assertion holds on both, but its margin is 27px locally and 15px in
 * CI. See `pxqPanel.visual.test.jsx` for that test's own note.
 *
 * This is also the reason no screenshot baselines are committed: a typeface
 * swap is not antialiasing noise that a pixel tolerance can absorb.
 */

// Browser mode reuses one page across test files, so `data-theme` set by one
// test would leak into the next. Reset to the app's own default: ThemeContext
// falls back to 'light' when localStorage has no `theme` key.
afterEach(() => {
  cleanup();
  document.documentElement.setAttribute('data-theme', 'light');
});

document.documentElement.setAttribute('data-theme', 'light');
