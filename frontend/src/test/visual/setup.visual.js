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
 * FONTS ARE DELIBERATELY *NOT* PINNED HERE — and NO assertion may depend on
 * which typeface won.
 *
 * The app loads Inter from the Google Fonts CDN in `index.html`. Browser mode
 * serves its own page and never runs `index.html`, so nothing loads it, and
 * `* { font-family: 'Inter', system-ui, -apple-system, sans-serif }` (index.css)
 * resolves against whatever the host happens to have. Measured in this very
 * Chromium, for the longest PxQ label at 12px/500:
 *
 *   'Inter'                       117.33px  <- NOT Inter: no machine involved
 *                                              here has it installed, so this
 *                                              is just the default `sans-serif`
 *   system-ui  (= Liberation Sans) 129.42px  <- what the stack ACTUALLY lands on
 *   the whole app stack            129.42px
 *
 * An earlier revision of this note claimed 117.33px was "Inter installed
 * system-wide". It is not — `fc-list | grep -i inter` finds nothing, and a
 * deliberately bogus family measures the same 117.33px. Do not reintroduce a
 * per-machine font claim here without measuring it.
 *
 * Pinning a font was considered and REJECTED. The repo's own
 * `public/fonts/Inter-Regular.ttf` is a 67 KB subset cut for pdfme's PDF
 * generation, not a web font: characters outside the subset (the "í" in
 * "envío") fall back mid-string, so it measures wider than real Inter. And
 * pinning would only HIDE typeface sensitivity rather than remove it — a
 * suite whose assertions hold in any environment is worth more than one that
 * holds in a environment we froze.
 *
 * So the rule for this suite is: assert what the design PROMISES, not what
 * today's typeface happens to produce. `.label` sets
 * `line-height: var(--leading-tight)`, so a line box is always 12 x 1.25 = 15px
 * regardless of typeface — that is assertable. Whether a given string needs one
 * line box or two is not, and no test may ask.
 *
 * This is also the reason no screenshot baselines are committed: a typeface
 * swap is not antialiasing noise that a pixel tolerance can absorb.
 */

/**
 * Escape hatch to REPRODUCE a wide-typeface runner locally.
 *
 * A wider fallback than the developer's is the single most likely way for this
 * suite to pass locally and fail in CI, and it has already happened once: two
 * geometry assertions were written against a label that fits on one line here
 * and wraps to two on ubuntu-latest. Being able to force that condition is what
 * turns "I think it is typeface-independent" into something checkable.
 *
 *   VITE_WIDE_FONT='Noto Sans Black' pnpm run test:visual
 *
 * The value is the family to force on every element, mirroring index.css's own
 * `*` rule so the override lands the same way the app's does. Pick a family
 * WIDER than the 144px `.pxqField` for the longest label — the probe above
 * measures 148.56px for 'Noto Sans Black', enough to force the wrap.
 * Unset (the default) changes nothing.
 */
const wideFont = import.meta.env.VITE_WIDE_FONT;
if (wideFont) {
  const override = document.createElement('style');
  override.textContent = `* { font-family: ${JSON.stringify(wideFont)} !important; }`;
  document.head.append(override);
}

// Browser mode reuses one page across test files, so `data-theme` set by one
// test would leak into the next. Reset to the app's own default: ThemeContext
// falls back to 'light' when localStorage has no `theme` key.
afterEach(() => {
  cleanup();
  document.documentElement.setAttribute('data-theme', 'light');
});

document.documentElement.setAttribute('data-theme', 'light');
