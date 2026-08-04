/**
 * Layer 1 — computed-style and geometry assertions for the `forms-tesla.css`
 * primitive, in real Chromium.
 *
 * These are deterministic: no font rasterisation, no antialiasing, no platform
 * variance. They read the same numbers the browser uses to paint, which is the
 * part jsdom cannot supply at any price — `getComputedStyle` there returns
 * declared-or-default values, `getBoundingClientRect()` returns zeros, and
 * `composes:` is never resolved at all.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fx from './fixtures.module.css';
import promo from '../../components/promociones/promociones.module.css';
import { tokenPx, tokenColor, setTheme, px, boxOf, contrastRatio, mount, verticalGapBetween } from './visualHelpers';

let host;

afterEach(() => {
  host?.remove();
  host = undefined;
});

describe('forms-tesla primitive — composition', () => {
  /**
   * The single most valuable assertion in this change.
   *
   * `composes:` is a build-time CSS-Modules feature: the class list emitted for
   * `.baseInput` must include BOTH the local class and the primitive's class.
   * In the jsdom project (`css: false`) the import is a no-op proxy, so this is
   * unverifiable there — a compose chain pointing at a class that no longer
   * exists produces a control with browser-default styling and NOTHING fails.
   * That is the silent regression this pins.
   */
  it('emits the primitive class alongside the local one (composes actually resolved)', () => {
    const classes = fx.baseInput.trim().split(/\s+/);

    expect(classes.length).toBeGreaterThanOrEqual(2);
    // The real consumer in the app composes TWO primitive classes (input + inputSm).
    expect(promo.pxqInput.trim().split(/\s+/).length).toBeGreaterThanOrEqual(3);
  });

  /**
   * Composition resolving is necessary but not sufficient — the composed class
   * also has to carry the primitive's declarations. A control that fell back to
   * user-agent styling has ~1px/2px padding and 0 radius, so these exact values
   * separate "styled by forms-tesla" from "styled by nobody".
   */
  it('a composed control computes the primitive padding, radius and background', () => {
    host = mount(`<input class="${fx.baseInput}" />`);
    const box = boxOf(host.firstElementChild);

    expect(box.paddingTop).toBe(tokenPx('--spacing-sm'));
    expect(box.paddingBottom).toBe(tokenPx('--spacing-sm'));
    expect(box.paddingLeft).toBe(tokenPx('--spacing-md'));
    expect(box.paddingRight).toBe(tokenPx('--spacing-md'));

    expect(px(box.borderRadius)).toBe(tokenPx('--radius-md'));
    expect(box.background).toBe(tokenColor('--cf-bg-card'));
    expect(box.color).toBe(tokenColor('--cf-text-primary'));
    expect(box.borderColor).toBe(tokenColor('--cf-border-default'));
    expect(box.minHeight).toBe(tokenPx('--input-height-base'));

    // Not the UA default. Pinned explicitly so a future fallback is loud.
    expect(box.paddingTop).toBeGreaterThan(2);
    expect(px(box.borderRadius)).toBeGreaterThan(0);
  });

  /**
   * Only the metrics the primitive still actually controls are asserted here.
   * `background` and `border` are deliberately NOT in this list: global
   * `!important` rules in `theme.css` take them away from every `select` and
   * `textarea` in the app. That is a real defect, and it is pinned as such in
   * `globalOverrides.visual.test.jsx` rather than quietly weakened here.
   */
  it('select and textarea share the input box metrics (one primitive, not three)', () => {
    host = mount(`
      <input class="${fx.baseInput}" />
      <select class="${fx.baseSelect}"></select>
      <textarea class="${fx.baseTextarea}"></textarea>
    `);
    const [input, select, textarea] = [...host.children].map(boxOf);

    for (const other of [select, textarea]) {
      expect(other.paddingTop).toBe(input.paddingTop);
      expect(other.paddingLeft).toBe(input.paddingLeft);
      expect(other.borderRadius).toBe(input.borderRadius);
    }

    // The textarea is deliberately two lines tall; everything else matches.
    expect(textarea.minHeight).toBe(input.minHeight * 2);
    expect(select.minHeight).toBe(input.minHeight);
  });
});

describe('forms-tesla primitive — focus state', () => {
  /**
   * The PxQ inputs shipped three times with NO focus style: keyboard users had
   * no way to tell where they were. `outline: none` is set by the primitive, so
   * if the replacement ring is ever dropped the control becomes silently
   * unfocusable-looking again. This is the pin against that.
   */
  it('focus produces a visible ring and moves the border colour', () => {
    host = mount(`<input class="${fx.baseInput}" />`);
    const el = host.firstElementChild;

    const resting = boxOf(el);
    expect(resting.boxShadow).toBe('none');

    el.focus();
    expect(document.activeElement).toBe(el);
    const focused = boxOf(el);

    // A ring exists at all.
    expect(focused.boxShadow).not.toBe('none');
    expect(focused.boxShadow).not.toBe('');
    // …and it is the accent ring, not an accidental leftover shadow.
    expect(focused.boxShadow).toContain(tokenColor('--cf-accent-blue-light'));

    // The border also moves, so the state survives if box-shadow is suppressed.
    expect(focused.borderColor).not.toBe(resting.borderColor);
    expect(focused.borderColor).toBe(tokenColor('--cf-accent-blue'));

    // `outline: none` is only acceptable BECAUSE of the ring above.
    expect(getComputedStyle(el).outlineStyle).toBe('none');
  });

  it('an invalid control keeps its red edge while focused (source order holds)', () => {
    host = mount(`<input class="${fx.errorInput}" />`);
    const el = host.firstElementChild;

    expect(boxOf(el).borderColor).toBe(tokenColor('--cf-accent-red'));

    el.focus();
    // The invalid rules come after `:focus` in the primitive at equal
    // specificity — if someone reorders the file, focus would repaint the
    // border blue and the error state would vanish exactly when the user is
    // interacting with the broken field.
    expect(boxOf(el).borderColor).toBe(tokenColor('--cf-accent-red'));
    expect(boxOf(el).boxShadow).not.toBe('none');
  });

  it('aria-invalid alone styles the control (a11y state cannot diverge from the visual)', () => {
    host = mount(`<input class="${fx.baseInput}" aria-invalid="true" />`);
    expect(boxOf(host.firstElementChild).borderColor).toBe(tokenColor('--cf-accent-red'));
  });
});

describe('forms-tesla primitive — dark mode', () => {
  beforeEach(() => setTheme('light'));

  it('token-driven colours actually change between themes and are never empty', () => {
    host = mount(`<input class="${fx.baseInput}" />`);
    const el = host.firstElementChild;

    const light = boxOf(el);
    setTheme('dark');
    const dark = boxOf(el);

    for (const value of [light.background, light.color, light.borderColor,
      dark.background, dark.color, dark.borderColor]) {
      expect(value).toBeTruthy();
      expect(value).not.toBe('rgba(0, 0, 0, 0)');
    }

    expect(dark.background).not.toBe(light.background);
    expect(dark.color).not.toBe(light.color);
    expect(dark.borderColor).not.toBe(light.borderColor);

    // Geometry is theme-independent — a theme switch must not reflow the form.
    expect(dark.paddingLeft).toBe(light.paddingLeft);
    expect(dark.minHeight).toBe(light.minHeight);
  });

  it('the control stays readable in both themes (text vs its own fill)', () => {
    host = mount(`<input class="${fx.baseInput}" />`);
    const el = host.firstElementChild;

    for (const theme of ['light', 'dark']) {
      setTheme(theme);
      const { color, background } = boxOf(el);
      // WCAG AA body text is 4.5:1. Asserted as a real ratio, not "the strings
      // differ" — two different-but-similar colours also "differ".
      expect(contrastRatio(color, background)).toBeGreaterThan(4.5);
    }
  });

  /**
   * The maintainer's least-confident case, made explicit.
   *
   * In dark mode the disabled fill is `--cf-bg-app` (#000000) while a card is
   * `--cf-bg-card` (#181818). So a disabled control INVERTS the light-mode
   * convention: instead of a greyed-out control that recedes, you get a hole
   * that is DARKER than the surface it sits on, and on a plain app background
   * it is the same colour as the page. The only thing separating it from the
   * page is a 1px `--cf-border-subtle` edge.
   *
   * The test pins the two facts that make or break it: the fill is the app
   * background, and the border must remain separable from that fill — because
   * if it ever stops being, the disabled control becomes literally invisible.
   */
  it('disabled in dark mode: the fill is the app background, so the border is the only separator', () => {
    setTheme('dark');
    host = mount(`
      <div style="background: var(--cf-bg-card)">
        <input class="${fx.baseInput}" />
        <input class="${fx.baseInput}" disabled />
      </div>
    `);
    const [enabled, disabled] = [...host.firstElementChild.children].map(boxOf);

    expect(disabled.background).toBe(tokenColor('--cf-bg-app'));
    expect(disabled.borderColor).toBe(tokenColor('--cf-border-subtle'));
    expect(disabled.color).toBe(tokenColor('--cf-text-muted'));

    // Darker than the card it sits on — the inversion, asserted rather than assumed.
    expect(disabled.background).not.toBe(enabled.background);

    // The border must not be the same colour as the fill, or the control
    // disappears entirely against the app background.
    expect(contrastRatio(disabled.borderColor, disabled.background)).toBeGreaterThan(1);
  });

  /**
   * KNOWN DEFECT — disabled text in dark mode is below the bar this suite sets.
   *
   * `--cf-text-muted` is `rgba(255, 255, 255, 0.4)` in dark mode and the
   * disabled fill is `--cf-bg-app` (#000000). Composited, the text actually
   * reaches the eye as `rgb(102, 102, 102)`, which is **3.66:1** — under the
   * 4.5:1 this file asserts everywhere else.
   *
   * This assertion USED TO PASS, and that was the bug: `contrastRatio()`
   * discarded the alpha channel and scored the text as opaque white on black,
   * i.e. 21:1 — the theoretical maximum. So the strongest possible score was
   * being reported for the weakest colour pair in the theme. Fixing the helper
   * did not create this defect, it revealed it.
   *
   * NOT fixed here, deliberately: the fix is a design-token change
   * (`--cf-text-muted` in the dark block of `design-tokens.css`) that repaints
   * every muted/placeholder/disabled surface in the app, so it belongs in its
   * own change with a designer in the loop — not smuggled in behind a test fix.
   *
   * Worth deciding explicitly rather than by accident: WCAG 1.4.3 EXEMPTS
   * inactive controls, so 3.66:1 is not a formal AA violation. But
   * `frontend/AGENTS.md`'s QA checklist says "text contrast meets WCAG AA"
   * with no carve-out, and this file applies 4.5 to every other pair. Either
   * raise the token or lower this bar on purpose — do not leave the two
   * disagreeing.
   *
   * ponytail: `--cf-text-muted` (dark) is 3.66:1 on `--cf-bg-app`; raise the
   * token or document the disabled-text exemption, then promote this to `it`.
   */
  it.fails('SHOULD: disabled text in dark mode clears 4.5:1 on the disabled fill', () => {
    setTheme('dark');
    host = mount(`<input class="${fx.baseInput}" disabled />`);
    const disabled = boxOf(host.firstElementChild);

    expect(contrastRatio(disabled.color, disabled.background)).toBeGreaterThan(4.5);
  });

  it('disabled in LIGHT mode recedes (fill is lighter than the card) — the opposite of dark', () => {
    setTheme('light');
    host = mount(`<input class="${fx.baseInput}" disabled />`);
    const disabled = boxOf(host.firstElementChild);

    expect(disabled.background).toBe(tokenColor('--cf-bg-app'));
    expect(contrastRatio(disabled.color, disabled.background)).toBeGreaterThan(2);
  });
});

describe('forms-tesla primitive — dense variant', () => {
  it('inputSm computes a genuinely smaller box than the base input', () => {
    host = mount(`
      <input class="${fx.baseInput}" />
      <input class="${fx.denseInput}" />
    `);
    const [base, dense] = [...host.children].map(boxOf);

    expect(dense.minHeight).toBeLessThan(base.minHeight);
    expect(dense.paddingTop).toBeLessThan(base.paddingTop);
    expect(dense.paddingLeft).toBeLessThan(base.paddingLeft);
    expect(dense.fontSize).toBeLessThan(base.fontSize);

    expect(dense.minHeight).toBe(tokenPx('--input-height-sm'));
    expect(dense.paddingTop).toBe(tokenPx('--spacing-xs'));
    expect(dense.paddingLeft).toBe(tokenPx('--spacing-sm'));

    // Only box metrics change. Colours, radius and border are inherited from
    // the base rule, so a dense control cannot drift away from a normal one.
    expect(dense.background).toBe(base.background);
    expect(dense.borderRadius).toBe(base.borderRadius);
    expect(dense.borderColor).toBe(base.borderColor);
  });

  /**
   * The maintainer was unsure whether a dense input lines up with a
   * `btn-tesla sm`. Token equality is necessary but NOT sufficient: the button
   * carries a 2px border and the input 1px, so if the box model ever stopped
   * being `border-box` the two would compute 32px vs 36px from identical
   * tokens. Both facts are asserted.
   */
  it('a dense input and a btn-tesla sm are the same rendered height', () => {
    expect(tokenPx('--input-height-sm')).toBe(tokenPx('--btn-height-sm'));

    host = mount(`
      <div style="display:flex; align-items:flex-end">
        <input class="${fx.denseInput}" />
        <button type="button" class="btn-tesla sm">Guardar</button>
      </div>
    `);
    const [input, button] = host.firstElementChild.children;

    expect(getComputedStyle(input).boxSizing).toBe('border-box');
    expect(getComputedStyle(button).boxSizing).toBe('border-box');

    // Real painted geometry, not the declared token.
    expect(input.getBoundingClientRect().height).toBe(button.getBoundingClientRect().height);
    expect(input.getBoundingClientRect().height).toBe(tokenPx('--input-height-sm'));
  });
});

describe('forms-tesla primitive — field pairing unit', () => {
  /**
   * `.field` binds a label to its control by proximity. The rule only works if
   * the caller uses a LARGER gap between units than `.field` uses inside one,
   * so the inner gap has to actually be one small step on the scale.
   */
  it('.field stacks label above control with the small inner gap', () => {
    host = mount(`
      <div class="${fx.baseField}">
        <label class="${fx.baseLabel}">Cantidad mínima</label>
        <input class="${fx.denseInput}" />
      </div>
    `);
    const field = host.firstElementChild;
    const [label, input] = field.children;

    expect(getComputedStyle(field).flexDirection).toBe('column');
    // Measured from real geometry — this is the number a reader perceives.
    expect(verticalGapBetween(label, input)).toBe(tokenPx('--spacing-xs'));
  });

  it('a label is allowed to wrap rather than truncate (Spanish labels lose meaning when cut)', () => {
    host = mount(`
      <div class="${fx.baseField}" style="width: 60px">
        <label class="${fx.baseLabel}">Costo de envío del bulto</label>
      </div>
    `);
    const label = host.firstElementChild.firstElementChild;
    const cs = getComputedStyle(label);

    expect(cs.textOverflow).not.toBe('ellipsis');
    expect(cs.whiteSpace).not.toBe('nowrap');
    // Forced narrow: it really does wrap to more than one line instead of
    // overflowing or being clipped.
    expect(label.getBoundingClientRect().height).toBeGreaterThan(px(cs.fontSize) * 1.5);
  });
});
