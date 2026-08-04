/**
 * Stylelint — rule 1 of the CSS convention guard: colors come from tokens.
 *
 * Evidence: `frontend/AGENTS.md` has said "NEVER hardcoded colors" for a long
 * time with nothing enforcing it, and the tree now carries ~3000 literal color
 * values across 146 of 170 CSS files — four unrelated purples and three
 * unrelated greens that no theme switch can reach.
 *
 * A RATCHET, not a big bang: `HARDCODED_COLOR_ALLOWLIST` grandfathers today's
 * offenders so this passes on the tree unmodified, and only NEW violations
 * fail. `css-guard/cssGuard.test.js` proves the list has no stale entries.
 * Only rules backed by a measured defect are enabled — a noisy config gets
 * disabled, and then we are worse off than with nothing.
 */

import {
  HARDCODED_COLOR_ALLOWLIST,
  TOKEN_DEFINITION_FILES,
} from './css-guard/allowlist.js';

/**
 * Literal `rgb()`/`rgba()`/`hsl()`/`hsla()`, but ONLY when the first argument
 * is a number. `rgba(var(--brand-primary-rgb), 0.1)` is token-derived and
 * legitimate, and stylelint's `function-disallowed-list` cannot tell the two
 * apart — it flags both. This regex can.
 */
const LITERAL_COLOR_FUNCTION = /\b(?:rgba?|hsla?)\(\s*[\d.]/i;

/**
 * Exported so the stale-entry test can run these with NO allowlist applied.
 * One definition means the ratchet and the check cannot drift apart.
 *
 * No exemption is configured for CSS system color keywords (`Highlight`,
 * `Canvas`, `ButtonText`) used in `forced-colors` fallbacks: verified
 * empirically that `color-named` does not flag them, so none is needed.
 */
export const colorRules = {
  'color-no-hex': [
    true,
    { message: 'Hardcoded hex color — use a design token, e.g. var(--cf-accent-blue)' },
  ],
  'color-named': [
    'never',
    { message: 'Hardcoded named color — use a design token from design-tokens.css' },
  ],
  'declaration-property-value-disallowed-list': [
    { '/.*/': [LITERAL_COLOR_FUNCTION] },
    {
      message:
        'Hardcoded rgb()/hsl() color — use a design token, or rgba(var(--token-rgb), a) for alpha',
    },
  ],
};

export default {
  // Token DEFINITION sites. Literal colors are the whole point of these files;
  // there is no token to defer to because this is where tokens are born.
  // Permanent and principled, NOT debt — distinct from the allowlist below.
  ignoreFiles: TOKEN_DEFINITION_FILES,

  rules: colorRules,

  // The ratchet. Every entry is debt with a paid-off date of "eventually".
  // Fix the CSS to remove an entry; never add one to silence a failure.
  overrides: [
    {
      files: HARDCODED_COLOR_ALLOWLIST,
      rules: {
        'color-no-hex': null,
        'color-named': null,
        'declaration-property-value-disallowed-list': null,
      },
    },
  ],
};
