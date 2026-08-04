/**
 * DEFECTS THE BROWSER FOUND — global legacy CSS defeats the forms-tesla primitive.
 *
 * `forms-tesla.css` is correct in isolation (see `formsPrimitive.visual.test.jsx`,
 * where a bare `<input>` computes exactly what the primitive declares). But the
 * app never renders a bare `<input>`. It renders `type="number"`, `type="text"`,
 * `<select>` and `<textarea>`, and for those there are older global rules that
 * win:
 *
 *   theme.css:197  select, option { background/color/border: … !important }
 *   theme.css:207  input[type="text"|"number"|"email"|"password"], textarea {
 *                    background/color/border: … !important;
 *                    border-radius: 4px; padding: 10px 14px; font-size: 14px }
 *   theme.css:230  …:focus { border-color: … !important;
 *                            box-shadow: 0 0 0 3px rgba(92,140,255,.1) }
 *
 * `input[type="number"]` has specificity (0,1,1) and beats the primitive's
 * single class (0,1,0) — and the `!important` declarations beat it outright.
 * The net effect is that on a REAL control the primitive contributes almost
 * nothing: padding, radius, font-size, colours and the focus ring all come from
 * `theme.css`, and the `inputSm` dense variant is entirely inert.
 *
 * WHY `it.fails()`
 * Each `it.fails` below states the invariant that SHOULD hold and records that
 * it currently does not. It executes for real: the day someone deletes those
 * global rules, the assertion starts passing, `it.fails` turns RED, and whoever
 * fixed it is told to promote the test. That is the opposite of a skipped test,
 * which would rot silently.
 *
 * These are NOT fixed here on purpose — this change adds verification, it does
 * not change what is verified. Fixing them means deleting global form rules
 * that ~56 unmigrated modules currently depend on, which is its own change.
 *
 * ponytail: remove the `.fails` markers here once theme.css's global form
 * control rules are retired; tracked as the forms-tesla adoption follow-up.
 */

import { describe, it, expect, afterEach } from 'vitest';
import fx from './fixtures.module.css';
import promo from '../../components/promociones/promociones.module.css';
import { tokenPx, tokenColor, px, boxOf, mount } from './visualHelpers';

let host;

afterEach(() => {
  host?.remove();
  host = undefined;
});

describe('KNOWN DEFECT — theme.css global rules outrank forms-tesla', () => {
  it('a bare input gets the primitive, so the primitive itself is fine', () => {
    host = mount(`<input class="${fx.baseInput}" />`);
    const box = boxOf(host.firstElementChild);

    expect(box.paddingLeft).toBe(tokenPx('--spacing-md'));
    expect(px(box.borderRadius)).toBe(tokenPx('--radius-md'));
    expect(box.borderColor).toBe(tokenColor('--cf-border-default'));
  });

  /**
   * The control the PxQ panel actually renders. Same class list as above, one
   * extra attribute, completely different result.
   */
  it('adding type="number" silently replaces the primitive box (the defect, asserted)', () => {
    host = mount(`
      <input class="${fx.baseInput}" />
      <input class="${fx.baseInput}" type="number" />
    `);
    const [bare, typed] = [...host.children].map(boxOf);

    // Identical class list…
    expect(host.children[0].className).toBe(host.children[1].className);
    // …different computed box.
    expect(typed.paddingLeft).not.toBe(bare.paddingLeft);
    expect(typed.borderRadius).not.toBe(bare.borderRadius);
    expect(typed.borderColor).not.toBe(bare.borderColor);

    // Exactly what theme.css:207 declares.
    expect(typed.paddingTop).toBe(10);
    expect(typed.paddingLeft).toBe(14);
    expect(px(typed.borderRadius)).toBe(4);
  });

  it.fails('SHOULD: a type="number" control keeps the primitive padding', () => {
    host = mount(`<input class="${fx.baseInput}" type="number" />`);
    expect(boxOf(host.firstElementChild).paddingLeft).toBe(tokenPx('--spacing-md'));
  });

  it.fails('SHOULD: a type="number" control keeps the primitive radius', () => {
    host = mount(`<input class="${fx.baseInput}" type="number" />`);
    expect(px(boxOf(host.firstElementChild).borderRadius)).toBe(tokenPx('--radius-md'));
  });

  it.fails('SHOULD: a select keeps the primitive border colour', () => {
    host = mount(`<select class="${fx.baseSelect}"></select>`);
    expect(boxOf(host.firstElementChild).borderColor).toBe(tokenColor('--cf-border-default'));
  });

  it.fails('SHOULD: a textarea keeps the primitive border colour', () => {
    host = mount(`<textarea class="${fx.baseTextarea}"></textarea>`);
    expect(boxOf(host.firstElementChild).borderColor).toBe(tokenColor('--cf-border-default'));
  });

  /**
   * The dense variant is the whole reason `.pxqInput` composes `inputSm`. On
   * the real control it changes nothing that is visible: padding and font-size
   * are both taken over by theme.css, and only `min-height` (which theme.css
   * does not set) survives — and min-height loses to the taller content box.
   */
  it('inputSm is inert on a real PxQ control — padding and font-size are overridden', () => {
    host = mount(`
      <input class="${promo.pxqInput}" type="number" />
      <input class="${fx.baseInput}" type="number" />
    `);
    const [dense, base] = [...host.children].map(boxOf);

    // The dense class IS in the class list…
    expect(promo.pxqInput.split(/\s+/).length).toBeGreaterThanOrEqual(3);
    // …and changes nothing about the painted box.
    expect(dense.paddingTop).toBe(base.paddingTop);
    expect(dense.paddingLeft).toBe(base.paddingLeft);
    expect(dense.fontSize).toBe(base.fontSize);
  });

  it.fails('SHOULD: a dense PxQ control computes the dense padding', () => {
    host = mount(`<input class="${promo.pxqInput}" type="number" />`);
    expect(boxOf(host.firstElementChild).paddingTop).toBe(tokenPx('--spacing-xs'));
  });

  /**
   * The maintainer asked directly whether the 32px input height is right in a
   * dense panel. The browser's answer: the panel never gets 32px.
   *
   * `min-height: 32px` survives, but theme.css's `padding: 10px 14px` plus
   * `font-size: 14px` make the CONTENT box taller than the minimum, so the
   * control lays out at 39.5px while the `btn-tesla sm` beside it is exactly
   * 32px. Every PxQ authoring row is misaligned by 7.5px.
   *
   * That 39.5px is ARITHMETIC, not a font metric, and the assertions below are
   * written to show it: 1px border + 10px padding + a 17.5px line box + 10px
   * padding + 1px border. The line box is 17.5px because the primitive's
   * `line-height: var(--leading-tight)` is UNITLESS (1.25), and a unitless
   * line-height resolves to `font-size x factor` without ever consulting the
   * font's ascent/descent metrics — the same property `pxqPanel.visual.test.jsx`
   * relies on for its 15px label lines. `line-height: normal` WOULD consult
   * them, so the tests reject it explicitly rather than assume it is absent.
   *
   * Verified across 9 families with deliberately extreme metrics (including
   * Noto Nastaliq Urdu, monospace and serif): the height is 39.5px in every
   * one. The literal `39.5` / `7.5` that used to be asserted here have been
   * replaced by the decomposition anyway — not because they were typeface
   * dependent, but because a bare literal fails on an unrelated
   * `--leading-tight` change and says nothing about why 39.5 is the number.
   */
  it('a real PxQ input does NOT line up with the btn-tesla sm beside it', () => {
    host = mount(`
      <div style="display:flex; align-items:flex-end">
        <input class="${promo.pxqInput}" type="number" />
        <button type="button" class="btn-tesla sm">Guardar</button>
      </div>
    `);
    const [input, button] = host.firstElementChild.children;
    const inputH = input.getBoundingClientRect().height;
    const buttonH = button.getBoundingClientRect().height;
    const cs = getComputedStyle(input);
    const box = boxOf(input);

    expect(buttonH).toBe(tokenPx('--btn-height-sm'));
    // The invariant that matters: the control is TALLER than the button it is
    // supposed to sit flush with.
    expect(inputH).toBeGreaterThan(buttonH);

    // The typeface-independence guarantee, asserted instead of assumed. If the
    // cascade ever leaves this control on `normal`, the height genuinely does
    // become a property of the runner's font stack and this suite must know.
    expect(cs.lineHeight).not.toBe('normal');

    // The discrepancy, still pinned EXACTLY — but derived from the cascade that
    // produces it, so the diff shows both the number and its cause.
    const derivedH =
      px(cs.borderTopWidth) +
      px(cs.paddingTop) +
      px(cs.lineHeight) +
      px(cs.paddingBottom) +
      px(cs.borderBottomWidth);

    expect(inputH).toBe(derivedH);

    // …and this is the mechanism: the dense variant DOES ask for 32px, and the
    // content box simply outgrows it.
    expect(box.minHeight).toBe(tokenPx('--input-height-sm'));
    expect(derivedH).toBeGreaterThan(box.minHeight);
  });

  it.fails('SHOULD: a real PxQ input is exactly as tall as a btn-tesla sm', () => {
    host = mount(`
      <div style="display:flex; align-items:flex-end">
        <input class="${promo.pxqInput}" type="number" />
        <button type="button" class="btn-tesla sm">Guardar</button>
      </div>
    `);
    const [input, button] = host.firstElementChild.children;
    expect(input.getBoundingClientRect().height).toBe(button.getBoundingClientRect().height);
  });

  /**
   * The primitive's focus ring is 2px of `--cf-accent-blue-light` with a
   * `--cf-accent-blue` border. On a typed control you get theme.css's 3px
   * hardcoded `rgba(92,140,255,.1)` ring and a `--brand-primary` border.
   *
   * A focus ring still EXISTS, which is what matters for accessibility — so
   * this is a consistency defect, not an a11y one. Asserted separately from the
   * "focus is visible at all" test so the two cannot be confused.
   */
  it('a typed control focuses with theme.css ring, not the primitive ring', () => {
    host = mount(`<input class="${fx.baseInput}" type="number" />`);
    const el = host.firstElementChild;

    el.focus();
    const focused = boxOf(el);

    // Still visible — the accessibility floor holds.
    expect(focused.boxShadow).not.toBe('none');
    // But it is the legacy ring: 3px spread, hardcoded colour.
    expect(focused.boxShadow).toContain('3px');
    expect(focused.boxShadow).not.toContain(tokenColor('--cf-accent-blue-light'));
    expect(focused.borderColor).not.toBe(tokenColor('--cf-accent-blue'));
  });

  it.fails('SHOULD: a typed control focuses with the primitive accent ring', () => {
    host = mount(`<input class="${fx.baseInput}" type="number" />`);
    host.firstElementChild.focus();
    expect(boxOf(host.firstElementChild).boxShadow).toContain(tokenColor('--cf-accent-blue-light'));
  });
});
