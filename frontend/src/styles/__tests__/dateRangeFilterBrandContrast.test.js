/**
 * The selected DateRangeFilter quick chip ("Mes actual") under the TP-Link
 * brand.
 *
 * It paints text on `--brand-primary-light`. Light-mode Teal (#4acbd6) on its
 * own light tint is ~1.8:1, so the text token it consumes must be one the
 * brand keeps readable on that tint, while resolving to the SAME colour as
 * before in the base theme (pixel-identical).
 *
 * Unit project runs jsdom with `css: false` and jsdom does not resolve `var()`,
 * so this resolves the tokens from the stylesheets themselves. The cascade is
 * simple and fixed here: `:root`, then `:root[data-theme]` (design-tokens.css,
 * then theme.css), then the brand block from brand-tplink.css.
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import postcss from 'postcss';

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const read = (rel) => postcss.parse(fs.readFileSync(path.join(SRC, rel), 'utf8'));

const declsOf = (root, selector) => {
  const out = {};
  root.walkRules((rule) => {
    if (rule.selector.trim() !== selector) return;
    rule.each((node) => {
      if (node.type === 'decl') out[node.prop] = node.value.trim();
    });
  });
  return out;
};

const tokensFor = (theme, { brand }) => {
  const files = ['styles/design-tokens.css', 'styles/theme.css'].map(read);
  const tokens = {};
  for (const root of files) Object.assign(tokens, declsOf(root, ':root'));
  for (const root of files) Object.assign(tokens, declsOf(root, `:root[data-theme="${theme}"]`));
  if (brand) {
    Object.assign(
      tokens,
      declsOf(read('styles/brand-tplink.css'), `[data-brand="tplink"][data-theme="${theme}"]`),
    );
  }
  return tokens;
};

/** Resolve `var(--x, fallback)` chains down to a literal. */
const resolve = (value, tokens, depth = 0) => {
  if (depth > 20) throw new Error(`var() cycle resolving ${value}`);
  const match = value.match(/^var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)$/);
  if (!match) return value;
  const [, name, fallback] = match;
  if (tokens[name] !== undefined) return resolve(tokens[name], tokens, depth + 1);
  if (fallback !== undefined) return resolve(fallback.trim(), tokens, depth + 1);
  throw new Error(`unresolved token ${name}`);
};

const hexToRgb = (hex) => {
  const h = hex.replace('#', '');
  const full = h.length === 3 ? [...h].map((c) => c + c).join('') : h;
  return [0, 2, 4].map((i) => Number.parseInt(full.slice(i, i + 2), 16));
};

const luminance = ([r, g, b]) => {
  const ch = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b);
};

const contrast = (a, b) => {
  const [hi, lo] = [luminance(hexToRgb(a)), luminance(hexToRgb(b))].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const chipRule = (selector) => declsOf(read('components/DateRangeFilter.module.css'), selector);
const ACTIVE = ['.btnFiltroRapido.activo', '.btnFiltroRapido.activo:hover'];

describe('DateRangeFilter active quick chip', () => {
  for (const selector of ACTIVE) {
    for (const theme of ['light', 'dark']) {
      it(`${selector} reaches WCAG AA under data-brand="tplink" (${theme})`, () => {
        const decls = chipRule(selector);
        const tokens = tokensFor(theme, { brand: true });
        const fg = resolve(decls.color, tokens);
        const bg = resolve(decls.background, tokens);
        expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
      });

      it(`${selector} keeps the base colours (${theme})`, () => {
        // Before the fix the chip text was --brand-primary; the base theme must
        // still paint exactly that.
        const decls = chipRule(selector);
        const tokens = tokensFor(theme, { brand: false });
        expect(resolve(decls.color, tokens)).toBe(resolve('var(--brand-primary)', tokens));
        expect(resolve(decls.background, tokens)).toBe(
          resolve('var(--brand-primary-light, var(--bg-hover))', tokens),
        );
      });
    }
  }
});
