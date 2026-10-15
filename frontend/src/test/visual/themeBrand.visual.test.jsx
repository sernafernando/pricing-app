/**
 * TP-Link brand theme, measured in Chromium.
 *
 * Two claims, kept apart on purpose:
 *
 *   1. The BASE theme is untouched. `themeTokensBaseline.json` is every custom
 *      property declared on `:root`, resolved in light and dark on `main`
 *      BEFORE the role-token layer existed. Re-expressing a token through a
 *      role token (`--primary: var(--brand-primary)`) is only safe if the
 *      resolved value stays byte-identical, so the whole set is compared, not
 *      a hand-picked sample that would miss the one that drifted.
 *   2. The BRAND (`data-brand="tplink"`) repaints the role tokens and keeps
 *      the text that sits on them readable, in both light and dark.
 *
 * The brand assertions pin a few anchor values of the final palette (primary,
 * text on primary, link, app background, header) and otherwise check contrast,
 * so retuning a secondary token does not fail the suite.
 */
import { describe, it, expect, afterEach } from 'vitest';
import baseline from './themeTokensBaseline.json';
import { setTheme, tokenColor, contrastRatio, mount } from './visualHelpers';

const THEMES = ['light', 'dark'];
const TEAL = 'rgb(74, 203, 214)';
const root = () => document.documentElement;
const resolved = (name) => getComputedStyle(root()).getPropertyValue(name).trim();
const setBrand = (brand) => root().setAttribute('data-brand', brand);

let host;

afterEach(() => {
  host?.remove();
  host = undefined;
  root().removeAttribute('data-brand');
});

describe('base theme is identical with the role-token layer in place', () => {
  for (const theme of THEMES) {
    it(`every :root token resolves as on main (${theme})`, () => {
      setTheme(theme);
      const drift = Object.entries(baseline)
        .filter(([, values]) => values[theme] !== undefined)
        .filter(([name, values]) => resolved(name) !== values[theme])
        .map(([name, values]) => `${name}: ${values[theme]} -> ${resolved(name)}`);
      expect(drift).toEqual([]);
    });

    it(`role tokens default to the current values (${theme})`, () => {
      setTheme(theme);
      expect(tokenColor('--on-brand-primary')).toBe(tokenColor('--text-inverse'));
      expect(tokenColor('--on-brand-primary-hover')).toBe(tokenColor('--text-inverse'));
      expect(tokenColor('--brand-focus-ring')).toBe(tokenColor('--border-focus'));
      expect(tokenColor('--brand-link')).toBe(tokenColor('--brand-primary'));
      expect(tokenColor('--brand-header-bg')).toBe(tokenColor('--cf-bg-topbar'));
    });
  }

  it('without data-brand the primary button keeps the base colours', () => {
    setTheme('light');
    host = mount('<button class="btn-tesla primary">Guardar</button>');
    const cs = getComputedStyle(host.firstElementChild);
    expect(cs.color).toBe(tokenColor('--text-inverse'));
    expect(cs.backgroundImage).toContain('rgb(62, 106, 225)');
  });
});

const FINAL = {
  light: {
    '--brand-primary': TEAL,
    '--on-brand-primary': 'rgb(27, 36, 41)',
    '--brand-link': 'rgb(0, 107, 117)',
    '--cf-bg-app': 'rgb(246, 248, 249)',
    '--brand-header-bg': 'rgb(255, 255, 255)',
  },
  dark: {
    '--brand-primary': TEAL,
    '--on-brand-primary': 'rgb(11, 26, 31)',
    '--brand-link': TEAL,
    '--cf-bg-app': 'rgb(8, 12, 14)',
    '--brand-header-bg': 'rgb(14, 20, 23)',
  },
};

// Global classes that used Teal as a text colour (or white text on Teal) and
// are rerouted by brand-tplink.css. [markup, role token the text must use].
const REROUTED = [
  ['<button class="btn-primary">Guardar</button>', '--on-brand-primary'],
  ['<button class="btn-primary-solid">Guardar</button>', '--on-brand-primary'],
  ['<button class="btn-tesla outline">Ver</button>', '--brand-link'],
  ['<button class="btn-outline">Ver</button>', '--brand-link'],
  ['<span class="badge-primary">Nuevo</span>', '--brand-link'],
  ['<button class="modal-tab active">Datos</button>', '--brand-link'],
  ['<table><thead class="table-tesla-head"><tr><th class="sorted">Col</th></tr></thead></table>', '--brand-link'],
];

describe('data-brand="tplink"', () => {
  for (const theme of THEMES) {
    describe(theme, () => {
      it('repaints the primary role to TP-Link Teal', () => {
        setTheme(theme);
        setBrand('tplink');
        expect(tokenColor('--brand-primary')).toBe(TEAL);
      });

      it('resolves the final palette anchors', () => {
        setTheme(theme);
        setBrand('tplink');
        const actual = Object.fromEntries(
          Object.keys(FINAL[theme]).map((name) => [name, tokenColor(name)]),
        );
        expect(actual).toEqual(FINAL[theme]);
      });

      it('reroutes Teal-as-text and text-on-Teal to the role tokens', () => {
        setTheme(theme);
        setBrand('tplink');
        const wrong = REROUTED.filter(([markup, token]) => {
          host?.remove();
          host = mount(markup);
          const el = host.querySelector('button, span, th');
          return getComputedStyle(el).color !== tokenColor(token);
        }).map(([markup]) => markup);
        expect(wrong).toEqual([]);
      });

      it('keeps text readable on the brand surfaces (WCAG AA 4.5:1)', () => {
        setTheme(theme);
        setBrand('tplink');
        const pairs = [
          ['--on-brand-primary', '--brand-primary'],
          ['--on-brand-primary-hover', '--brand-primary-hover'],
          ['--cf-text-primary', '--cf-bg-app'],
          ['--cf-text-primary', '--cf-bg-card'],
          ['--cf-text-secondary', '--cf-bg-card'],
          ['--text-primary', '--bg-secondary'],
          ['--brand-link', '--cf-bg-card'],
        ];
        const failing = pairs
          .map(([fg, bg]) => [fg, bg, contrastRatio(tokenColor(fg), tokenColor(bg))])
          .filter(([, , ratio]) => ratio < 4.5)
          .map(([fg, bg, ratio]) => `${fg} on ${bg}: ${ratio.toFixed(2)}`);
        expect(failing).toEqual([]);
      });

      it('the focus ring is visible against the app background (3:1)', () => {
        setTheme(theme);
        setBrand('tplink');
        expect(
          contrastRatio(tokenColor('--brand-focus-ring'), tokenColor('--cf-bg-app')),
        ).toBeGreaterThanOrEqual(3);
      });

      it('the primary button paints Teal with readable text', () => {
        setTheme(theme);
        setBrand('tplink');
        host = mount('<button class="btn-tesla primary">Guardar</button>');
        const cs = getComputedStyle(host.firstElementChild);
        expect(cs.color).toBe(tokenColor('--on-brand-primary'));
        expect(cs.backgroundImage).toContain(TEAL);
      });

      it('the TP-Link logo keeps its 22px minimum height', () => {
        setTheme(theme);
        setBrand('tplink');
        host = mount('<img class="tplink-brand-logo" alt="TP-Link" src="/brand/tplink-logo-white.png" />');
        expect(host.firstElementChild.getBoundingClientRect().height).toBeGreaterThanOrEqual(22);
      });
    });
  }
});
