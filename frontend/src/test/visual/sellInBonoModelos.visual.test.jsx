/**
 * Sell-in models bonus, per-model values (T23b) -- real CSS, real Chromium: each model row keeps its name, its value
 * input and its remove button on one line inside a panel-width column; the read-only chips fit too.
 *
 *   pnpm exec vitest run --project=visual sellInBonoModelos
 *   VITE_SELLIN_MODELOS_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellInBonoModelos   (also saves screenshots)
 */
import { describe, it, expect } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import SellInBonoModelos from '../../components/sellIn/SellInBonoModelos';

const MODELOS = [
  { itemId: 4512, label: 'SW-8 · Switch 8 bocas Gigabit administrable', montoUnit: '4.5', porcentaje: '' },
  { itemId: 4513, label: 'AP-AX3000 · Access point Wi-Fi 6', montoUnit: '', porcentaje: '' },
  { itemId: 4514, label: 'RT-1200 · Router', montoUnit: '12', porcentaje: '' },
];
const SHOTS_DIR = import.meta.env.VITE_SELLIN_MODELOS_SHOTS_DIR;

describe('SellInBonoModelos (visual)', () => {
  for (const theme of ['light', 'dark']) {
    it(`keeps each model row on one line in a 480px panel, ${theme}`, async () => {
      await page.viewport(1280, 800);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      const valores = { tipo: 'por_unidad', moneda: 'USD', modelos: MODELOS };
      await render(
        <div style={{ width: 480, padding: 16 }}>
          <SellInBonoModelos valores={valores} disabled={false} onChange={() => {}} />
          <div style={{ height: 24 }} />
          <SellInBonoModelos valores={valores} disabled onChange={() => {}} />
        </div>,
      );
      const [edicion, lectura] = document.querySelectorAll('ul[aria-label="Modelos del bono"]');
      for (const li of edicion.querySelectorAll('li')) {
        const [nombre, input, boton] = [li.querySelector('span'), li.querySelector('input'), li.querySelector('button')];
        const tops = [nombre, input, boton].map((el) => el.getBoundingClientRect());
        expect(Math.abs(tops[1].top - tops[2].top)).toBeLessThan(12); // input and remove button side by side
        expect(tops[2].right).toBeLessThanOrEqual(edicion.getBoundingClientRect().right + 1);
      }
      expect(edicion.scrollWidth).toBeLessThanOrEqual(edicion.clientWidth + 1);
      expect(lectura.scrollWidth).toBeLessThanOrEqual(lectura.clientWidth + 1);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/sellin-modelos-${theme}.png` });
    });
  }
});
