/**
 * Publicaciones ML's `?` help (ShortcutsHelp) -- real CSS, real Chromium (pubml-atajos S3).
 *
 * jsdom does no layout, so the unit suite pins the keys and this file pins the layout:
 *  - on a 1440x900 desktop the groups sit side by side in 2-3 columns and the whole set fits without scrolling,
 *    Lista's Alt / Shift with Enter or Space (pubml-atajos-faltantes S2) included;
 *  - inside a group the keycaps share one column, so every description starts on the same line;
 *  - with text 12% wider than this browser's own font (CI's Chromium has DejaVu, wider than local fonts) it still fits
 *    1440x900, and the key pairs of Copiar and Abrir un filtro stay on one line;
 *  - on a 390 phone the groups stack in one column and nothing overflows sideways.
 *
 *   pnpm exec vitest run --project=visual shortcutsHelp
 *   VITE_ATAJOS_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual shortcutsHelp   (also saves screenshots)
 */
import { describe, it, expect } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import ShortcutsHelp from '../../components/publicacionesMl/ShortcutsHelp';

const SHOTS_DIR = import.meta.env.VITE_ATAJOS_SHOTS_DIR;
// Wider letters stand in for a wider system font. The margin is relative to the font this browser has (a fixed
// letter-spacing would add to CI's already wider font), as the other visual tests' CI_FONT_MARGIN.
const CI_FONT_MARGIN = 1.12;
const SAMPLE = 'Abrir la publicación en el panel de vendedores Ctrl+Shift+1';

/** Letter-spacing (px) that makes `element`'s text CI_FONT_MARGIN times wider on SAMPLE, on top of its own spacing. */
function widerSpacing(element) {
  const own = Number.parseFloat(getComputedStyle(element).letterSpacing) || 0;
  const probe = document.createElement('span');
  probe.textContent = SAMPLE;
  probe.style.whiteSpace = 'nowrap';
  element.append(probe);
  const width = probe.getBoundingClientRect().width;
  probe.remove();
  return own + (width * (CI_FONT_MARGIN - 1)) / SAMPLE.length;
}
const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

const groupsOf = () => Array.from(document.querySelectorAll('.modal-body-tesla section'));
const distinct = (values) => new Set(values.map((value) => Math.round(value))).size;

async function open(width, height, theme) {
  await page.viewport(width, height);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  const screen = await render(<ShortcutsHelp onClose={() => {}} />);
  await expect.element(screen.getByRole('heading', { name: 'Atajos de teclado' })).toBeVisible();
  if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/atajos-${width}-${theme}.png` });
  return screen;
}

describe('ShortcutsHelp (visual)', () => {
  for (const theme of ['light', 'dark']) {
    it(`lays the groups out in 2-3 columns that fit 1440x900 without scrolling, ${theme}`, async () => {
      await open(1440, 900, theme);
      const body = document.querySelector('.modal-body-tesla');
      expect(body.scrollHeight).toBeLessThanOrEqual(body.clientHeight + 1);

      // The last keys added to Lista are on screen, inside the body, with no scroll.
      const bodyBox = body.getBoundingClientRect();
      for (const key of ['Alt+Espacio', 'Shift+Espacio']) {
        const kbd = Array.from(body.querySelectorAll('kbd')).find((candidate) => candidate.textContent === key);
        expect(kbd.getBoundingClientRect().bottom).toBeLessThanOrEqual(bodyBox.bottom);
      }

      const groups = groupsOf();
      expect(groups.length).toBeGreaterThanOrEqual(5);
      const columns = distinct(groups.map((group) => group.getBoundingClientRect().left));
      expect(columns).toBeGreaterThanOrEqual(2);
      expect(columns).toBeLessThanOrEqual(3);

      // A wider font still fits without scrolling, and the short groups' key pairs do not wrap.
      const text = widerSpacing(body.querySelector('dd'));
      const keys = widerSpacing(body.querySelector('kbd'));
      const wider = document.createElement('style');
      wider.textContent = `.modal-body-tesla { letter-spacing: ${text}px; } .modal-body-tesla kbd { letter-spacing: ${keys}px; }`;
      document.head.append(wider);
      try {
        await frame();
        expect(body.scrollHeight, `${CI_FONT_MARGIN}x wider font`).toBeLessThanOrEqual(body.clientHeight + 1);
        for (const name of ['Copiar', 'Abrir un filtro']) {
          const group = groupsOf().find((section) => section.querySelector('h3').textContent === name);
          for (const term of group.querySelectorAll('dt')) {
            const tops = Array.from(term.querySelectorAll('kbd')).map((kbd) => kbd.getBoundingClientRect().top);
            expect(distinct(tops), `${name}: ${term.textContent}`).toBe(1);
          }
        }
      } finally {
        wider.remove();
        await frame();
      }

      // One keycap column per group: every description of a group starts at the same x.
      for (const group of groups) {
        const starts = Array.from(group.querySelectorAll('dd')).map((dd) => dd.getBoundingClientRect().left);
        expect(distinct(starts)).toBe(1);
      }
    });

    it(`stacks the groups in one column on a 390 phone, ${theme}`, async () => {
      await open(390, 844, theme);
      const groups = groupsOf();
      expect(distinct(groups.map((group) => group.getBoundingClientRect().left))).toBe(1);
      const body = document.querySelector('.modal-body-tesla');
      expect(body.scrollWidth).toBeLessThanOrEqual(body.clientWidth + 1);
      for (const kbd of document.querySelectorAll('.modal-body-tesla kbd')) {
        expect(kbd.getBoundingClientRect().right).toBeLessThanOrEqual(body.getBoundingClientRect().right);
      }
    });
  }
});
