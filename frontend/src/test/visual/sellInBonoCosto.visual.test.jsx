/**
 * Sell-in cost bonus form (T25e) -- real CSS, real Chromium: with the cost base selected, the base selector, the fixed
 * kind/currency, the "Incluye IVA" checkbox with its help and the sale-date inputs fit a panel-width form without
 * overflowing it, in light and dark.
 *
 *   pnpm exec vitest run --project=visual sellInBonoCosto
 *   VITE_SELLIN_COSTO_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellInBonoCosto   (also saves screenshots)
 */
import { describe, it, expect } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import SellInBonoForm from '../../components/sellIn/SellInBonoForm';
import { BASE_COSTO, BONO_VACIO, conBase } from '../../components/sellIn/sellInBonoValores';

const SHOTS_DIR = import.meta.env.VITE_SELLIN_COSTO_SHOTS_DIR;

describe('SellInBonoForm cost base (visual)', () => {
  for (const theme of ['light', 'dark']) {
    it(`fits the cost-base fields in a 480px panel, ${theme}`, async () => {
      await page.viewport(1280, 900);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      const valores = { ...conBase({ ...BONO_VACIO, marca: 'TP-LINK' }, BASE_COSTO), porcentaje: '3', incluyeIva: true };
      await render(
        <div data-testid="panel" style={{ width: 480, padding: 16 }}>
          <SellInBonoForm valores={valores} onChange={() => {}} marcas={['TP-LINK']} />
        </div>,
      );
      const panel = document.querySelector('[data-testid="panel"]');
      const check = document.querySelector('input[type="checkbox"]');
      const etiqueta = check.closest('label').getBoundingClientRect();
      const caja = check.getBoundingClientRect();
      expect(check.checked).toBe(true);
      expect(caja.width).toBeGreaterThan(0);
      expect(Math.abs(caja.top + caja.height / 2 - (etiqueta.top + etiqueta.height / 2))).toBeLessThan(3); // box and text on one line
      const desde = document.querySelector('input[id$="-desde"]').getBoundingClientRect();
      const hasta = document.querySelector('input[id$="-hasta"]').getBoundingClientRect();
      expect(Math.abs(desde.top - hasta.top)).toBeLessThan(2); // sale dates side by side
      expect(hasta.right).toBeLessThanOrEqual(panel.getBoundingClientRect().right);
      expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/sellin-costo-${theme}.png` });
    });
  }
});
