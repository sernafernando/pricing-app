/**
 * Sell-in bonus shared cap (T24d) -- real CSS, real Chromium: the two cap inputs sit side by side inside a panel-width
 * form without overflowing it, with their full labels, in light and dark.
 *
 *   pnpm exec vitest run --project=visual sellInBonoTope
 *   VITE_SELLIN_TOPE_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellInBonoTope   (also saves screenshots)
 */
import { describe, it, expect } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import SellInBonoForm from '../../components/sellIn/SellInBonoForm';
import { BONO_VACIO } from '../../components/sellIn/sellInBonoValores';

const SHOTS_DIR = import.meta.env.VITE_SELLIN_TOPE_SHOTS_DIR;

describe('SellInBonoForm cap fields (visual)', () => {
  for (const theme of ['light', 'dark']) {
    it(`keeps both cap inputs on one row in a 480px panel, ${theme}`, async () => {
      await page.viewport(1280, 900);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      const valores = { ...BONO_VACIO, marca: 'LENOVO', montoUnit: '25', topeUnidades: '1200', topeMonto: '3000' };
      await render(
        <div data-testid="panel" style={{ width: 480, padding: 16 }}>
          <SellInBonoForm valores={valores} onChange={() => {}} marcas={['LENOVO']} />
        </div>,
      );
      const panel = document.querySelector('[data-testid="panel"]');
      const unidades = document.querySelector('input[id$="-tope-u"]').getBoundingClientRect();
      const monto = document.querySelector('input[id$="-tope-m"]').getBoundingClientRect();
      expect(Math.abs(unidades.top - monto.top)).toBeLessThan(2); // side by side
      expect(monto.right).toBeLessThanOrEqual(panel.getBoundingClientRect().right);
      expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/sellin-tope-${theme}.png` });
    });
  }
});
