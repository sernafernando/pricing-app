/**
 * Helpers shared by the browser-mode visual suite.
 *
 * Everything here reads REAL computed values out of Chromium. Nothing is
 * parsed out of a CSS source file: reading the stylesheet would only prove the
 * text we already wrote is still the text we wrote, which is exactly the blind
 * spot this suite exists to close.
 */

/**
 * Resolve a design token to the value the browser actually paints with.
 *
 * NOT `getComputedStyle(root).getPropertyValue('--x')`. That returns the token's
 * own computed value, which resolves nested `var()` but performs NO unit or
 * colour normalisation: `--input-height-sm` comes back as the string `'2rem'`
 * and `--cf-bg-app` as `'#f9fafb'`. Comparing those against a real property's
 * computed value (`'32px'`, `'rgb(249, 250, 251)'`) fails for reasons that have
 * nothing to do with the styling being correct.
 *
 * So we do what the cascade does: APPLY the token to a probe element and read
 * the normalised result back. `paddingTop` and `color` are used as the carriers
 * because both normalise aggressively (any length -> px, any colour -> rgb()).
 * The probe is attached to `document.body` so it inherits the live `:root`
 * tokens for the theme currently set.
 *
 * Expected values in the tests are therefore derived from the token scale
 * rather than hardcoded: changing a token's VALUE is a deliberate design change
 * and should not fail these tests, while breaking the wiring that delivers it
 * to the control should.
 */
const readThroughProbe = (property, name) => {
  const probe = document.createElement('div');
  // Assigned through the camelCase CSSStyleDeclaration accessor, NOT
  // `setProperty()`: that one takes kebab-case and silently ignores
  // `'paddingTop'`, which would make every length token read back as 0.
  probe.style[property] = `var(${name})`;
  document.body.append(probe);
  try {
    return getComputedStyle(probe)[property];
  } finally {
    probe.remove();
  }
};

/** A length token, normalised to a number of CSS pixels. `--radius-md` -> 6. */
export const tokenPx = (name) => Number.parseFloat(readThroughProbe('paddingTop', name));

/** A colour token, normalised to the `rgb()` / `rgba()` form. */
export const tokenColor = (name) => readThroughProbe('color', name);

/** The token's raw computed value, for the rare case the literal text matters. */
export const tokenRaw = (name, el = document.documentElement) =>
  getComputedStyle(el).getPropertyValue(name).trim();

/** Set the theme the way the app does — ThemeContext writes this attribute. */
export const setTheme = (theme) => document.documentElement.setAttribute('data-theme', theme);

/** Numeric value of a computed length, e.g. '8px' -> 8. */
export const px = (value) => Number.parseFloat(value);

/** Every computed box metric that matters for a form control, in one object. */
export const boxOf = (el) => {
  const cs = getComputedStyle(el);
  return {
    paddingTop: px(cs.paddingTop),
    paddingRight: px(cs.paddingRight),
    paddingBottom: px(cs.paddingBottom),
    paddingLeft: px(cs.paddingLeft),
    borderRadius: cs.borderTopLeftRadius,
    background: cs.backgroundColor,
    color: cs.color,
    borderColor: cs.borderTopColor,
    borderWidth: px(cs.borderTopWidth),
    minHeight: px(cs.minHeight),
    fontSize: px(cs.fontSize),
    boxShadow: cs.boxShadow,
    boxSizing: cs.boxSizing,
  };
};

/** Parse 'rgb(r, g, b)' / 'rgba(r, g, b, a)' into [r, g, b, a]. */
export const rgba = (color) => {
  const parts = color.match(/[\d.]+/g);
  if (!parts) throw new Error(`not a parseable color: ${color}`);
  const [r, g, b, a = '1'] = parts;
  return [Number(r), Number(g), Number(b), Number(a)];
};

/**
 * WCAG relative luminance of an OPAQUE colour.
 *
 * Takes a 3-channel triple on purpose. It used to be handed the 4-channel
 * output of `rgba()` and destructured only `[r, g, b]`, which silently threw
 * the alpha away: `--cf-text-muted` in dark mode is `rgba(255,255,255,0.4)`
 * and was scored as fully opaque white, i.e. luminance 1.0 against a black
 * fill — a ratio of 21:1, the theoretical maximum, for text that actually
 * renders at 3.66:1. Every `> 4.5` assertion downstream passed without
 * deserving it. Composite first (see `over`), then call this.
 */
const luminance = ([r, g, b]) => {
  const channel = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
};

/**
 * Alpha-composite a colour over an opaque backdrop (simple source-over).
 *
 * This is the whole point: a human eye never receives `rgba(255,255,255,0.4)`,
 * it receives that colour already blended with whatever is behind it —
 * `rgb(102,102,102)` over black. Contrast is a property of what reaches the
 * eye, so the blend has to happen BEFORE luminance, not be assumed away.
 */
const over = ([r, g, b, a], [br, bg, bb]) => [
  r * a + br * (1 - a),
  g * a + bg * (1 - a),
  b * a + bb * (1 - a),
];

/**
 * WCAG contrast ratio between two computed colors, 1 (identical) to 21.
 * Used to check a control is actually SEPARABLE from what it sits on, which is
 * a stronger and more honest claim than "the two strings differ".
 *
 * `colorA` is the foreground and MAY be translucent — it gets composited over
 * `colorB` first. `colorB` is the backdrop and must be opaque: a translucent
 * backdrop has no colour of its own without the entire stack painted beneath
 * it, and quietly assuming it is opaque is exactly the bug this function used
 * to have. So it throws instead of inventing an answer — an accessibility
 * assertion that lies is worse than no assertion.
 */
export const contrastRatio = (colorA, colorB) => {
  const fg = rgba(colorA);
  const bg = rgba(colorB);

  if (bg[3] < 1) {
    throw new Error(
      `contrastRatio() needs an opaque backdrop, got ${colorB}. ` +
        'Measure against the element that actually paints behind it.',
    );
  }

  const backdrop = bg.slice(0, 3);
  const la = luminance(over(fg, backdrop));
  const lb = luminance(backdrop);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
};

/**
 * Mount raw markup into a live, laid-out container.
 *
 * Appended to `document.body` (not to a detached node) on purpose: a detached
 * subtree has no layout, so `getBoundingClientRect()` would return zeros and we
 * would be back to the jsdom problem we are trying to escape.
 */
export const mount = (html) => {
  const host = document.createElement('div');
  host.setAttribute('data-visual-host', '');
  host.innerHTML = html;
  document.body.append(host);
  return host;
};

/** Vertical gap between two stacked elements, measured from real geometry. */
export const verticalGapBetween = (upper, lower) =>
  lower.getBoundingClientRect().top - upper.getBoundingClientRect().bottom;
