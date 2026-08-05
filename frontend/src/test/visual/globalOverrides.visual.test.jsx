/**
 * theme.css's global form rules as a ZERO-SPECIFICITY BASELINE.
 *
 * `forms-tesla.css` is correct in isolation (see `formsPrimitive.visual.test.jsx`,
 * where a bare `<input>` computes exactly what the primitive declares). But the
 * app never renders a bare `<input>`: it renders `type="number"`, `type="text"`,
 * `<select>` and `<textarea>`, and theme.css has rules for all of those. This
 * file measures the CASCADE between the two — the part neither file can verify
 * about itself.
 *
 * The two mechanisms that used to make the global rules win, and what replaced
 * them:
 *
 *   1. `!important` on `background` / `color` / `border`. Removed — nothing in
 *      that section carries it any more.
 *   2. `input[type="number"]` is specificity (0,1,1), which beats a CSS-Modules
 *      class like `.pxqInput` at (0,1,0). Every selector in that section is now
 *      wrapped in `:where()`, which contributes ZERO specificity, so they all
 *      compute (0,0,0) and any single class wins.
 *
 * The rules still EXIST, deliberately: ~55 modules have not migrated to
 * `composes:` yet and some declare only part of the control box, so deleting
 * them would drop those controls to browser defaults. The last test in this file
 * is the guard for that half — it pins that an unmigrated control with no
 * competing class is still painted.
 *
 * The values in theme.css were left untouched, which is why that guard can be
 * an equality assertion rather than a range.
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

describe('theme.css global form rules are a zero-specificity baseline', () => {
  it('a bare input gets the primitive, so the primitive itself is fine', () => {
    host = mount(`<input class="${fx.baseInput}" />`);
    const box = boxOf(host.firstElementChild);

    expect(box.paddingLeft).toBe(tokenPx('--spacing-md'));
    expect(px(box.borderRadius)).toBe(tokenPx('--radius-md'));
    expect(box.borderColor).toBe(tokenColor('--cf-border-default'));
  });

  /**
   * The control the PxQ panel actually renders. Same class list as above, one
   * extra attribute — and now the same result, which is the whole point.
   *
   * Asserted two ways on purpose. Equality against the bare control is the
   * cascade claim (`type=` no longer changes who wins); equality against the
   * TOKENS is the value claim (both are the primitive's box, not both wrong in
   * the same way). Either alone would pass if theme.css started painting the
   * bare control too.
   */
  it('a type attribute no longer replaces the primitive box', () => {
    host = mount(`
      <input class="${fx.baseInput}" />
      <input class="${fx.baseInput}" type="number" />
      <input class="${fx.baseInput}" type="text" />
      <input class="${fx.baseInput}" type="date" />
    `);
    const [bare, ...typed] = [...host.children].map(boxOf);

    for (const control of typed) {
      expect(control.paddingTop).toBe(bare.paddingTop);
      expect(control.paddingLeft).toBe(bare.paddingLeft);
      expect(control.borderRadius).toBe(bare.borderRadius);
      expect(control.borderColor).toBe(bare.borderColor);
      expect(control.background).toBe(bare.background);
      expect(control.color).toBe(bare.color);
      expect(control.fontSize).toBe(bare.fontSize);

      // …and the shared value is the primitive's, not theme.css's 10/14 box
      // with its 4px radius.
      expect(control.paddingTop).toBe(tokenPx('--spacing-sm'));
      expect(control.paddingLeft).toBe(tokenPx('--spacing-md'));
      expect(px(control.borderRadius)).toBe(tokenPx('--radius-md'));
      expect(control.borderColor).toBe(tokenColor('--cf-border-default'));
      expect(control.background).toBe(tokenColor('--cf-bg-card'));
      expect(control.color).toBe(tokenColor('--cf-text-primary'));
    }
  });

  /**
   * `select` and `textarea` were never a specificity problem — those selectors
   * are (0,0,1) and always lost to a class. It was purely the `!important` on
   * `background` / `color` / `border` that took these three properties away, so
   * those three are exactly what is asserted.
   */
  it('a select keeps the primitive background, colour and border', () => {
    host = mount(`<select class="${fx.baseSelect}"></select>`);
    const box = boxOf(host.firstElementChild);

    expect(box.borderColor).toBe(tokenColor('--cf-border-default'));
    expect(box.background).toBe(tokenColor('--cf-bg-card'));
    expect(box.color).toBe(tokenColor('--cf-text-primary'));
  });

  /**
   * NOT part of the `:where()` change and NOT theme.css's doing.
   * `design-tokens.css` draws a custom chevron on every `select:not([multiple])`
   * and reserves room for it with `padding-right: 36px !important`, at (0,1,1).
   * `!important` beats specificity whatever the selector looks like, so it also
   * beats the primitive — which asks for `--spacing-md` on all four sides.
   *
   * Deliberately NOT fixed here: dropping that `!important` would let the
   * primitive's 16px win and run the select's text under the chevron, which is
   * worse than the inconsistency. The real fix belongs in `forms-tesla.css`
   * (reserve chevron space in `.select` itself), and this change is forbidden
   * from touching that file.
   *
   * ponytail: `.select` cannot control its own `padding-right` — the global
   * chevron rule in design-tokens.css holds it at 36px with `!important`. Give
   * `forms-tesla.css`'s `.select` the chevron affordance, then drop the
   * `!important` and promote this to `it`.
   */
  it.fails('SHOULD: a select keeps the primitive padding on all four sides', () => {
    host = mount(`<select class="${fx.baseSelect}"></select>`);
    expect(boxOf(host.firstElementChild).paddingRight).toBe(tokenPx('--spacing-md'));
  });

  it('a textarea keeps the primitive background, colour and border', () => {
    host = mount(`<textarea class="${fx.baseTextarea}"></textarea>`);
    const box = boxOf(host.firstElementChild);

    expect(box.borderColor).toBe(tokenColor('--cf-border-default'));
    expect(box.background).toBe(tokenColor('--cf-bg-card'));
    expect(box.color).toBe(tokenColor('--cf-text-primary'));
  });

  /**
   * The dense variant is the whole reason `.pxqInput` composes `inputSm`.
   * It used to contribute nothing visible: `padding` and `font-size` were both
   * taken over by theme.css, leaving only `min-height`, which then lost to a
   * content box that had grown taller than it.
   *
   * Both halves are asserted: the dense box really is smaller than the base
   * one, and it is smaller by the exact amounts the variant declares.
   */
  it('the dense variant actually applies on a real PxQ control', () => {
    host = mount(`
      <input class="${promo.pxqInput}" type="number" />
      <input class="${fx.baseInput}" type="number" />
    `);
    const [dense, base] = [...host.children].map(boxOf);

    // The dense class IS in the class list…
    expect(promo.pxqInput.split(/\s+/).length).toBeGreaterThanOrEqual(3);

    // …and it now changes the painted box.
    expect(dense.paddingTop).toBeLessThan(base.paddingTop);
    expect(dense.paddingLeft).toBeLessThan(base.paddingLeft);
    expect(dense.fontSize).toBeLessThan(base.fontSize);

    expect(dense.paddingTop).toBe(tokenPx('--spacing-xs'));
    expect(dense.paddingLeft).toBe(tokenPx('--spacing-sm'));
    expect(dense.fontSize).toBe(tokenPx('--font-xs'));
    expect(dense.minHeight).toBe(tokenPx('--input-height-sm'));

    // Only box metrics change — the dense control cannot drift away from the
    // normal one on colour or radius.
    expect(dense.borderRadius).toBe(base.borderRadius);
    expect(dense.borderColor).toBe(base.borderColor);
    expect(dense.background).toBe(base.background);
  });

  /**
   * The maintainer asked directly whether the 32px input height is right in a
   * dense panel. The browser's answer used to be that the panel never GOT 32px:
   * `min-height: 32px` survived, but theme.css's `padding: 10px 14px` plus
   * `font-size: 14px` made the content box 39.5px, so every authoring row sat
   * 7.5px out of line with the `btn-tesla sm` beside it.
   *
   * The height is asserted three ways because equality alone is weak here — two
   * controls can match by both being wrong. So: it equals the button, it equals
   * the token both of them are supposed to come from, AND it is the sum of the
   * box the cascade actually produced, which is what makes the number
   * explainable rather than merely observed.
   *
   * That last decomposition also depends on `line-height` being UNITLESS
   * (`--leading-tight` = 1.25), which resolves to `font-size x factor` without
   * consulting the font's ascent/descent metrics. `line-height: normal` WOULD
   * consult them, so it is rejected explicitly rather than assumed absent —
   * otherwise this assertion would quietly become typeface-dependent.
   */
  it('a real PxQ input is exactly as tall as the btn-tesla sm beside it', () => {
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

    expect(buttonH).toBe(tokenPx('--btn-height-sm'));
    expect(inputH).toBe(buttonH);
    expect(inputH).toBe(tokenPx('--input-height-sm'));

    expect(cs.lineHeight).not.toBe('normal');

    // Derived from the cascade that produces it, so a future regression shows
    // both the number and its cause. The content box now fits INSIDE the
    // minimum instead of outgrowing it, so `min-height` is what decides.
    const contentH =
      px(cs.borderTopWidth) +
      px(cs.paddingTop) +
      px(cs.lineHeight) +
      px(cs.paddingBottom) +
      px(cs.borderBottomWidth);

    expect(contentH).toBeLessThanOrEqual(boxOf(input).minHeight);
    expect(inputH).toBe(boxOf(input).minHeight);
  });

  /**
   * The primitive's focus ring is `--border-2` of `--cf-accent-blue-light` with
   * a `--cf-accent-blue` border. A typed control used to get theme.css's 3px
   * hardcoded `rgba(92,140,255,.1)` ring and a `--brand-primary` border
   * instead, because the `:focus` rules sat at (0,2,1) with `!important` on
   * `border-color`.
   *
   * The resting state is measured first: `boxShadow: none` before focus is what
   * makes "a ring appeared" mean something rather than "a ring exists".
   */
  it('a typed control focuses with the primitive accent ring', () => {
    host = mount(`<input class="${fx.baseInput}" type="number" />`);
    const el = host.firstElementChild;

    const resting = boxOf(el);
    expect(resting.boxShadow).toBe('none');

    el.focus();
    expect(document.activeElement).toBe(el);
    const focused = boxOf(el);

    // A ring exists at all — the accessibility floor.
    expect(focused.boxShadow).not.toBe('none');
    // …and it is the primitive's, at the primitive's width.
    expect(focused.boxShadow).toContain(tokenColor('--cf-accent-blue-light'));
    expect(focused.boxShadow).toContain(`${tokenPx('--border-2')}px`);
    expect(focused.borderColor).toBe(tokenColor('--cf-accent-blue'));
    expect(focused.borderColor).not.toBe(resting.borderColor);
  });

  /**
   * THE OTHER HALF, and the riskier one.
   *
   * De-specifying was chosen over deleting precisely so that the ~55 modules
   * which have not migrated keep their controls painted. If someone later
   * deletes these rules — or "cleans up" the `:where()` in a way that drops
   * them — those controls silently fall back to browser defaults, which is a
   * far wider regression than the bug this file used to pin.
   *
   * So the baseline values are asserted as LITERALS on purpose. They are not
   * tokens on the design scale and must not be migrated onto it: they are
   * frozen legacy values whose only job is to stay exactly what they were while
   * the migration finishes. A UA default here would be ~1px/2px padding, 0
   * radius and no border colour of its own, so these numbers separate "the
   * baseline still applies" from "nobody is styling this".
   */
  it('an unmigrated control with no competing class still gets the baseline', () => {
    host = mount(`
      <input type="number" />
      <input type="text" />
      <input type="date" />
      <textarea></textarea>
      <select></select>
    `);
    const [number, text, date, textarea, select] = [...host.children].map(boxOf);

    for (const control of [number, text, date, textarea]) {
      expect(control.paddingTop).toBe(10);
      expect(control.paddingLeft).toBe(14);
      expect(px(control.borderRadius)).toBe(4);
      expect(control.fontSize).toBe(14);
      expect(control.borderWidth).toBe(1);
    }

    // `select` has always had its own tighter box in that section.
    expect(select.paddingTop).toBe(8);
    expect(select.paddingLeft).toBe(12);
    expect(px(select.borderRadius)).toBe(4);

    // Not the user-agent default. Pinned explicitly so a fallback is loud.
    for (const control of [number, text, date, textarea, select]) {
      expect(control.paddingTop).toBeGreaterThan(2);
      expect(px(control.borderRadius)).toBeGreaterThan(0);
      expect(control.borderColor).toBe(tokenColor('--border-secondary'));
      expect(control.background).toBe(tokenColor('--bg-primary'));
      expect(control.color).toBe(tokenColor('--text-primary'));
    }
  });

  /**
   * The baseline's focus state, same reasoning: it is the only focus indicator
   * an unmigrated control has, and `outline: none` is set right beside it. Lose
   * the ring and keyboard users on ~55 modules get nothing at all.
   */
  it('an unmigrated control still gets the baseline focus ring', () => {
    host = mount('<input type="number" /><input type="date" />');

    for (const el of host.children) {
      expect(boxOf(el).boxShadow).toBe('none');
      el.focus();
      const focused = boxOf(el);

      expect(focused.boxShadow).not.toBe('none');
      expect(focused.boxShadow).toContain('3px');
      expect(focused.borderColor).toBe(tokenColor('--brand-primary'));
      el.blur();
    }
  });
});
