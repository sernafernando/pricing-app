/**
 * The measuring instruments, measured.
 *
 * WHY THIS FILE EXISTS
 * `contrastRatio()` shipped with the alpha channel silently discarded: `rgba()`
 * returns four channels and `luminance()` destructured three. Every colour with
 * transparency was therefore scored as if it were fully opaque, and
 * `--cf-text-muted` in dark mode — `rgba(255, 255, 255, 0.4)` — was graded as
 * pure white on a black fill. That is 21:1, the theoretical MAXIMUM, for text
 * that reaches the eye at 3.66:1. Four `> 4.5` accessibility assertions passed
 * on that number without deserving it.
 *
 * Nothing in the suite could have caught it, because a helper that inflates
 * every ratio makes every assertion that uses it greener, not redder. An
 * accessibility assertion that lies is worse than no assertion, so the helper
 * now gets its own pins: the numbers below are fixed points of the WCAG formula
 * (not tokens, not typeface metrics), so they are legitimate literals.
 */

import { describe, it, expect } from 'vitest';
import { contrastRatio, rgba, px } from './visualHelpers';

describe('contrastRatio — alpha is composited, not discarded', () => {
  const BLACK = 'rgb(0, 0, 0)';
  const WHITE = 'rgb(255, 255, 255)';

  it('opaque black against opaque white is the 21:1 maximum', () => {
    expect(contrastRatio(WHITE, BLACK)).toBeCloseTo(21, 6);
    // Symmetric: which argument is lighter must not matter.
    expect(contrastRatio(BLACK, WHITE)).toBeCloseTo(21, 6);
  });

  it('an identical pair is 1:1', () => {
    expect(contrastRatio(BLACK, BLACK)).toBeCloseTo(1, 6);
    expect(contrastRatio(WHITE, WHITE)).toBeCloseTo(1, 6);
  });

  /**
   * THE regression pin. `rgba(255,255,255,0.4)` over black composites to
   * `rgb(102,102,102)` (0.4 x 255), whose WCAG ratio against black is 3.657.
   * If the alpha is ever dropped again this returns 21 and fails here first,
   * instead of quietly re-inflating the a11y assertions elsewhere.
   */
  it('a translucent foreground scores its composited colour, not its opaque one', () => {
    const muted = 'rgba(255, 255, 255, 0.4)';

    expect(contrastRatio(muted, BLACK)).toBeCloseTo(3.66, 2);
    // Emphatically NOT the opaque reading.
    expect(contrastRatio(muted, BLACK)).toBeLessThan(contrastRatio(WHITE, BLACK));
  });

  it('alpha 1 is indistinguishable from the opaque form', () => {
    expect(contrastRatio('rgba(255, 255, 255, 1)', BLACK)).toBeCloseTo(contrastRatio(WHITE, BLACK), 6);
  });

  it('a fully transparent foreground is invisible — 1:1 with its backdrop', () => {
    expect(contrastRatio('rgba(255, 255, 255, 0)', BLACK)).toBeCloseTo(1, 6);
    expect(contrastRatio('rgba(0, 0, 0, 0)', WHITE)).toBeCloseTo(1, 6);
  });

  it('lowering alpha moves the ratio monotonically toward 1', () => {
    const ratios = [1, 0.8, 0.6, 0.4, 0.2, 0].map((a) =>
      contrastRatio(`rgba(255, 255, 255, ${a})`, BLACK),
    );

    for (let i = 1; i < ratios.length; i += 1) {
      expect(ratios[i]).toBeLessThan(ratios[i - 1]);
    }
    expect(ratios.at(0)).toBeCloseTo(21, 6);
    expect(ratios.at(-1)).toBeCloseTo(1, 6);
  });

  /**
   * The backdrop is the one colour that CANNOT be guessed: its own appearance
   * depends on the entire stack painted beneath it, which a single computed
   * value does not carry. Assuming it opaque is precisely the bug above, so the
   * helper refuses rather than inventing a plausible number.
   */
  it('refuses a translucent backdrop instead of assuming it is opaque', () => {
    expect(() => contrastRatio(WHITE, 'rgba(0, 0, 0, 0.5)')).toThrow(/opaque backdrop/);
    // The foreground being translucent is fine — only the backdrop is refused.
    expect(() => contrastRatio('rgba(255, 255, 255, 0.5)', BLACK)).not.toThrow();
  });
});

describe('rgba / px — parsing contracts the helpers above depend on', () => {
  it('rgba() reports four channels, defaulting alpha to 1', () => {
    expect(rgba('rgb(1, 2, 3)')).toEqual([1, 2, 3, 1]);
    expect(rgba('rgba(1, 2, 3, 0.25)')).toEqual([1, 2, 3, 0.25]);
  });

  it('rgba() throws on something that is not a colour', () => {
    expect(() => rgba('none')).toThrow(/not a parseable color/);
  });

  it('px() reads a length and reports NaN for a keyword', () => {
    expect(px('17.5px')).toBe(17.5);
    // `line-height: normal` lands here, and NaN is what makes the geometry
    // tests fail loudly instead of comparing against a silent 0.
    expect(px('normal')).toBeNaN();
  });
});
