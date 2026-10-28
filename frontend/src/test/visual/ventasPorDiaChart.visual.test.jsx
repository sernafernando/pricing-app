/**
 * Métricas ML "Ventas por día" (audit B10) -- real CSS, real Chromium. jsdom does no layout, so the unit tests prove
 * the copy and this file proves the layout: 14 bars in one row inside the card, only the highest and lowest day show
 * their amount, every date and "N ops" pill on one line, nothing overflowing sideways.
 *
 *   pnpm exec vitest run --project=visual ventasPorDiaChart
 *   VITE_VENTAS_DIA_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual ventasPorDiaChart   (also saves screenshots)
 */
import { describe, it, expect } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import VentasPorDiaChart from '../../components/metricasMl/VentasPorDiaChart';

const GROSS = [
  9_120_000.5, 8_412_330, 12_450_210.75, 7_980_000, 10_015_440, 3_105_880.2, 6_330_000, 8_912_340, 9_870_000, 11_200_400,
  5_430_000, 7_777_777.77, 9_001_002, 10_500_000,
];
const OPS = [47, 41, 63, 38, 52, 17, 33, 47, 50, 58, 29, 40, 46, 55];
const SHOTS_DIR = import.meta.env.VITE_VENTAS_DIA_SHOTS_DIR;

describe('VentasPorDiaChart (visual)', () => {
  for (const [width, height] of [
    [1280, 800],
    [1920, 1080],
  ]) {
    for (const theme of ['light', 'dark']) {
      it(`keeps 14 bars in one row with one-line labels at ${width}px, ${theme}`, async () => {
        await page.viewport(width, height);
        setTheme(theme);
        document.body.style.background = 'var(--cf-bg-app)';
        const screen = await render(
          <div style={{ padding: 24 }}>
            <VentasPorDiaChart
              period={{ date_from: '2026-09-17', date_to: '2026-09-30' }}
              kpis={{ gross: { series: GROSS }, operations: { series: OPS } }}
            />
          </div>,
        );
        await expect.element(screen.getByRole('heading', { name: 'Ventas por día' })).toBeVisible();

        const card = document.querySelector('section[aria-labelledby="ventas-por-dia-titulo"]');
        const dias = [...card.querySelectorAll('li')];
        expect(dias).toHaveLength(14);
        const tops = new Set(dias.map((d) => Math.round(d.getBoundingClientRect().top)));
        expect(tops.size).toBe(1); // one row
        const cardRect = card.getBoundingClientRect();
        for (const d of dias) {
          expect(d.getBoundingClientRect().right).toBeLessThanOrEqual(cardRect.right);
          for (const el of d.querySelectorAll('span[class*="date"], span[class*="ops"]')) {
            expect(el.getBoundingClientRect().height).toBeLessThanOrEqual(22);
            expect(el.scrollWidth).toBeLessThanOrEqual(el.clientWidth + 1);
          }
        }
        const visibles = dias.filter((d) => getComputedStyle(d.querySelector('span[class*="value"]')).visibility === 'visible');
        expect(visibles.map((d) => d.dataset.extremo).sort()).toEqual(['max', 'min']);
        for (const d of visibles) {
          const valor = d.querySelector('span[class*="value"]');
          expect(valor.scrollWidth).toBeLessThanOrEqual(valor.clientWidth + 1); // the amount is never cut
        }
        expect(card.scrollWidth).toBeLessThanOrEqual(card.clientWidth + 1);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);

        if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/ventas-por-dia-${theme}-${width}.png` });
      });
    }
  }
});
