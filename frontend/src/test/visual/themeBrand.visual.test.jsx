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
import { setTheme, tokenColor, tokenRaw, contrastRatio, mount } from './visualHelpers';
import facet from '../../components/kit/FacetChips.module.css';
import switchChip from '../../components/kit/SwitchChip.module.css';
import segmented from '../../components/kit/SegmentedControl.module.css';
import alertsChip from '../../components/ventasMl/AlertsFilterChip.module.css';
import includeToggles from '../../components/ventasMl/IncludeToggles.module.css';
import packPanel from '../../components/ventasMl/PackDetailPanel.module.css';

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

const DEEP_TEAL = 'rgb(0, 107, 117)'; // #006b75
const LIGHT_TEAL = 'rgb(111, 214, 223)'; // #6fd6df

const FINAL = {
  light: {
    '--brand-primary': TEAL,
    '--on-brand-primary': 'rgb(27, 36, 41)',
    '--brand-link': DEEP_TEAL,
    '--cf-bg-app': 'rgb(245, 250, 251)',
    '--bg-secondary': 'rgb(245, 250, 251)',
    '--cf-bg-card': 'rgb(255, 255, 255)',
    '--brand-header-bg': 'rgb(255, 255, 255)',
  },
  dark: {
    '--brand-primary': TEAL,
    '--on-brand-primary': 'rgb(11, 26, 31)',
    '--brand-link': LIGHT_TEAL,
    '--cf-bg-app': 'rgb(14, 20, 23)',
    '--bg-secondary': 'rgb(14, 20, 23)',
    '--cf-bg-card': 'rgb(27, 37, 41)',
    '--metricas-head-bg': 'rgb(35, 47, 53)',
    '--cf-border-subtle': 'rgb(42, 56, 62)',
    '--brand-header-bg': 'rgb(14, 20, 23)',
  },
};

// Teal is a FILL only. Every role that paints teal as text, icon or border
// resolves to the readable teal for the mode instead.
const TEAL_AS_TEXT = [
  '--brand-link',
  '--brand-focus-ring',
  '--primary',
  '--accent-text',
  '--teal-text',
  '--cf-accent-teal',
  '--color-teal',
  '--cf-accent-blue',
];
const TEXT_TEAL = { light: DEEP_TEAL, dark: LIGHT_TEAL };

const POSITIVE = ['--success', '--success-text', '--tone-success-fg', '--money-positive', '--cf-saldo-positive', '--cf-accent-green'];
const NEGATIVE = ['--danger', '--error', '--error-text', '--cf-danger', '--tone-danger-fg', '--money-negative', '--cf-saldo-negative', '--cf-accent-red'];
const NUMBERS = {
  light: { positive: 'rgb(10, 92, 61)', negative: 'rgb(166, 31, 31)' },
  dark: { positive: 'rgb(95, 224, 165)', negative: 'rgb(255, 138, 138)' },
};

// Soft tinted badge backgrounds, solid so contrast is measurable.
const BADGE_BG = {
  light: { success: 'rgb(230, 245, 238)', danger: 'rgb(253, 236, 236)', warning: 'rgb(255, 246, 214)' },
  dark: { success: 'rgb(19, 45, 32)', danger: 'rgb(50, 19, 19)', warning: 'rgb(50, 44, 17)' },
};
const BADGE_TOKENS = {
  success: ['--success-bg', '--tone-success-bg', '--cf-ml-delivered-bg'],
  danger: ['--error-bg', '--tone-danger-bg', '--cf-ml-cancelled-bg'],
  warning: ['--warning-bg', '--tone-warning-bg', '--cf-ml-not-delivered-bg'],
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

      it('uses Teal only as a fill: text/icon/border roles resolve to the readable teal', () => {
        setTheme(theme);
        setBrand('tplink');
        const wrong = TEAL_AS_TEXT.filter((name) => tokenColor(name) !== TEXT_TEAL[theme]);
        expect(wrong).toEqual([]);
        const card = tokenColor('--cf-bg-card');
        const app = tokenColor('--cf-bg-app');
        expect(contrastRatio(TEXT_TEAL[theme], card)).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(TEXT_TEAL[theme], app)).toBeGreaterThanOrEqual(4.5);
      });

      it('paints positive and negative numbers with the brand success/danger text', () => {
        setTheme(theme);
        setBrand('tplink');
        const wrong = [
          ...POSITIVE.filter((n) => tokenColor(n) !== NUMBERS[theme].positive),
          ...NEGATIVE.filter((n) => tokenColor(n) !== NUMBERS[theme].negative),
        ];
        expect(wrong).toEqual([]);
      });

      it('keeps status badges on soft tinted backgrounds with readable text', () => {
        setTheme(theme);
        setBrand('tplink');
        const wrong = Object.entries(BADGE_TOKENS).flatMap(([tone, names]) =>
          names.filter((n) => tokenColor(n) !== BADGE_BG[theme][tone]).map((n) => `${n}: ${tokenColor(n)}`),
        );
        expect(wrong).toEqual([]);
        const pairs = [
          ['--success-text', '--success-bg'],
          ['--tone-success-fg', '--tone-success-bg'],
          ['--error-text', '--error-bg'],
          ['--tone-danger-fg', '--tone-danger-bg'],
          ['--warning-text', '--warning-bg'],
          ['--tone-warning-fg', '--tone-warning-bg'],
          ['--cf-ml-delivered-text', '--cf-ml-delivered-bg'],
          ['--cf-ml-cancelled-text', '--cf-ml-cancelled-bg'],
          ['--cf-ml-not-delivered-text', '--cf-ml-not-delivered-bg'],
        ];
        const failing = pairs
          .map(([fg, bg]) => [fg, bg, contrastRatio(tokenColor(fg), tokenColor(bg))])
          .filter(([, , ratio]) => ratio < 4.5)
          .map(([fg, bg, ratio]) => `${fg} on ${bg}: ${ratio.toFixed(2)}`);
        expect(failing).toEqual([]);
      });

      it('separates surfaces by tone, not shadow', () => {
        setTheme(theme);
        setBrand('tplink');
        for (const name of ['--cf-card-shadow', '--cf-card-shadow-hover', '--cf-shadow-card', '--shadow-sm']) {
          expect(tokenRaw(name), name).toBe('none');
        }
        expect(tokenColor('--cf-bg-card')).not.toBe(tokenColor('--cf-bg-app'));
      });

      it('secondary and muted text stay readable on cards and table group headers', () => {
        setTheme(theme);
        setBrand('tplink');
        const pairs = [
          ['--cf-text-secondary', '--cf-bg-card'],
          ['--cf-text-tertiary', '--cf-bg-card'],
          ['--cf-text-muted', '--cf-bg-card'],
          ['--cf-text-primary', '--metricas-head-bg'],
          ['--cf-text-secondary', '--metricas-head-bg'],
          ['--text-secondary', '--bg-secondary'],
        ];
        const failing = pairs
          .map(([fg, bg]) => [fg, bg, contrastRatio(tokenColor(fg), tokenColor(bg))])
          .filter(([, , ratio]) => ratio < 4.5)
          .map(([fg, bg, ratio]) => `${fg} on ${bg}: ${ratio.toFixed(2)}`);
        expect(failing).toEqual([]);
      });

      it('meaningful borders reach 3:1 (focus ring on card, strong border on card)', () => {
        setTheme(theme);
        setBrand('tplink');
        const card = tokenColor('--cf-bg-card');
        expect(contrastRatio(tokenColor('--brand-focus-ring'), card)).toBeGreaterThanOrEqual(3);
        expect(contrastRatio(tokenColor('--cf-border-strong'), card)).toBeGreaterThanOrEqual(3);
      });

      it('draws the 2px Teal accent line under the top bar', () => {
        setTheme(theme);
        setBrand('tplink');
        host = mount('<header data-sidebar-hidden="false" data-sidebar-expanded="true">x</header>');
        expect(getComputedStyle(host.firstElementChild).boxShadow).toBe(`${TEAL} 0px -2px 0px 0px inset`);
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

      it('the brand font inherits: an unclassed child keeps a monospace container font', () => {
        setTheme(theme);
        setBrand('tplink');
        host = mount('<div style="font-family: monospace"><span>12.345</span></div>');
        const container = host.firstElementChild;
        const child = container.firstElementChild;
        expect(getComputedStyle(child).fontFamily).toBe(getComputedStyle(container).fontFamily);
        expect(getComputedStyle(host).fontFamily).toContain('Aktiv Grotesk');
      });

      it('form controls take the brand font', () => {
        setTheme(theme);
        setBrand('tplink');
        host = mount('<button>Ok</button><input /><select></select><textarea></textarea>');
        const fonts = [...host.children].map((el) => getComputedStyle(el).fontFamily);
        expect(fonts.every((font) => font.includes('Aktiv Grotesk'))).toBe(true);
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

// The kit's selected state (facet chip, switch chip, segmented option, alert
// switch, include checkboxes) used to read the MONEY token, so it stayed blue
// under the brand. It now reads semantic selection tokens that default to the
// same money colour in the base theme.
const mountSelected = () => {
  host = mount(`
    <button class="${facet.chip} ${facet.chipActive}">Todas</button>
    <button class="${switchChip.chip} ${switchChip.on}">Flex</button>
    <div class="${segmented.group}"><button class="${segmented.option} ${segmented.active}">Mes</button></div>
    <button class="${alertsChip.toggle} ${alertsChip.toggleOn}"><span class="${alertsChip.track}"></span></button>
    <label class="${includeToggles.toggle}"><input type="checkbox" checked /></label>
    <button class="${packPanel.memberButton}">2000014907031737</button>
  `);
  const q = (sel) => host.querySelector(sel);
  return {
    facet: getComputedStyle(q(`.${facet.chipActive}`)),
    switchOn: getComputedStyle(q(`.${switchChip.on}`)),
    segmented: getComputedStyle(q(`.${segmented.active}`)),
    track: getComputedStyle(q(`.${alertsChip.track}`)),
    checkbox: getComputedStyle(q('input')),
    member: getComputedStyle(q(`.${packPanel.memberButton}`)),
  };
};

describe('kit selection state: base unchanged', () => {
  for (const theme of THEMES) {
    it(`selection tokens default to the money/card colours (${theme})`, () => {
      setTheme(theme);
      expect(tokenColor('--selection-fill')).toBe(tokenColor('--money-headline'));
      expect(tokenColor('--selection-border')).toBe(tokenColor('--money-headline'));
      expect(tokenColor('--selection-accent')).toBe(tokenColor('--money-headline'));
      expect(tokenColor('--on-selection-fill')).toBe(tokenColor('--cf-bg-card'));
    });

    it(`selected controls paint exactly as before (${theme})`, () => {
      setTheme(theme);
      const c = mountSelected();
      const money = tokenColor('--money-headline');
      const card = tokenColor('--cf-bg-card');
      expect([c.facet.backgroundColor, c.facet.borderTopColor, c.facet.color]).toEqual([money, money, card]);
      expect([c.switchOn.backgroundColor, c.switchOn.color]).toEqual([money, card]);
      expect(c.segmented.color).toBe(money);
      expect(c.track.backgroundColor).toBe(money);
      expect(c.checkbox.accentColor).toBe(money);
      expect(c.member.color).toBe(tokenColor('--brand-primary'));
    });
  }
});

// Stitch mockup, selected filter chip: light = tint #e3f7f9 with deep teal
// text; dark = #0f2e33 with light teal text and a Teal border.
const SELECTED_CHIP = {
  light: { bg: 'rgb(227, 247, 249)', fg: DEEP_TEAL },
  dark: { bg: 'rgb(15, 46, 51)', fg: LIGHT_TEAL, border: TEAL },
};

describe('kit selection state under data-brand="tplink"', () => {
  for (const theme of THEMES) {
    it(`selected chips match the mockup (${theme})`, () => {
      setTheme(theme);
      setBrand('tplink');
      const c = mountSelected();
      const want = SELECTED_CHIP[theme];
      for (const chip of [c.facet, c.switchOn]) {
        expect(chip.backgroundColor).toBe(want.bg);
        expect(chip.color).toBe(want.fg);
        if (want.border) expect(chip.borderTopColor).toBe(want.border);
        expect(contrastRatio(chip.color, chip.backgroundColor)).toBeGreaterThanOrEqual(4.5);
      }
    });

    it(`strong selection marks use the readable teal (${theme})`, () => {
      setTheme(theme);
      setBrand('tplink');
      const c = mountSelected();
      const card = tokenColor('--cf-bg-card');
      expect(c.segmented.color).toBe(TEXT_TEAL[theme]);
      expect(contrastRatio(c.segmented.color, card)).toBeGreaterThanOrEqual(4.5);
      expect(c.track.backgroundColor).toBe(TEXT_TEAL[theme]);
      expect(contrastRatio(c.track.backgroundColor, card)).toBeGreaterThanOrEqual(3);
      expect(c.checkbox.accentColor).toBe(TEXT_TEAL[theme]);
    });

    it(`pack member links read as links, not Teal text (${theme})`, () => {
      setTheme(theme);
      setBrand('tplink');
      const c = mountSelected();
      expect(c.member.color).toBe(TEXT_TEAL[theme]);
      expect(contrastRatio(c.member.color, c.member.backgroundColor)).toBeGreaterThanOrEqual(4.5);
    });
  }
});
