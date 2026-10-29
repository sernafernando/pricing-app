/**
 * Sell-out monto total reparto (T26d) -- real CSS, real Chromium: the summary, the share rows ("%" / "Monto fijo",
 * value, amount, remove) and the live totals fit a panel-width section without overflowing it, editable and
 * read-only, with a positive and a negative (deduction) total, in light and dark.
 *
 *   pnpm exec vitest run --project=visual sellOutReparto
 *   VITE_SELLOUT_REPARTO_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellOutReparto   (also saves screenshots)
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import SellOutReparto from '../../components/sellOut/SellOutReparto';
import { CAMPANA_MONTO_TOTAL, CAMPANA_MONTO_TOTAL_NEGATIVA } from '../../components/sellOut/sellOutFixtures';

vi.mock('../../services/api', () => ({ default: { get: vi.fn() }, productosAPI: { listar: vi.fn() } }));
vi.mock('../../services/sellOutAPI', () => ({ sellOutAPI: { repartir: vi.fn() } }));

const NEGATIVA_CON_REPARTO = {
  ...CAMPANA_MONTO_TOTAL_NEGATIVA,
  items: [
    { item_id: 5001, codigo: '20XW00A1AR', descripcion: 'Lenovo ThinkPad E14 Gen 5 i5 16GB 512GB', monto_unit: null, reparto_porcentaje: '60.0000', reparto_monto: null },
    { item_id: 5002, codigo: '82XB0038AR', descripcion: 'Lenovo IdeaPad Slim 3', monto_unit: null, reparto_porcentaje: null, reparto_monto: '-2000000.00' },
  ],
  resumen: {
    ...CAMPANA_MONTO_TOTAL_NEGATIVA.resumen,
    reparto: { asignado: '-10197245.00', asignado_sin_ventas: '-2000000.00', sin_asignar: '-3464830.00', motivo: null },
  },
};

const CASOS = [
  ['editable', CAMPANA_MONTO_TOTAL, true],
  ['negativa', NEGATIVA_CON_REPARTO, true],
  ['lectura', CAMPANA_MONTO_TOTAL, false],
];

const SHOTS_DIR = import.meta.env.VITE_SELLOUT_REPARTO_SHOTS_DIR;

describe('SellOutReparto (visual)', () => {
  for (const theme of ['light', 'dark']) {
    for (const [nombre, campana, editable] of CASOS) {
      it(`fits the ${nombre} reparto in a 480px panel, ${theme}`, async () => {
        await page.viewport(1280, 900);
        setTheme(theme);
        document.body.style.background = 'var(--cf-bg-app)';
        await render(
          <div data-testid="panel" style={{ width: 480, padding: 16, background: 'var(--cf-bg-card)' }}>
            <SellOutReparto campana={campana} editable={editable} onGuardado={() => {}} />
          </div>,
        );
        const panel = document.querySelector('[data-testid="panel"]');
        const derecha = panel.getBoundingClientRect().right;
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        for (const control of panel.querySelectorAll('select, input, button, td')) {
          expect(control.getBoundingClientRect().right).toBeLessThanOrEqual(derecha);
        }
        if (editable) {
          const modo = panel.querySelector('select').getBoundingClientRect();
          const valor = panel.querySelector('input[type="number"]').getBoundingClientRect();
          expect(Math.abs(modo.top + modo.height / 2 - (valor.top + valor.height / 2))).toBeLessThan(3); // one line
        }
        if (campana.monto_total.startsWith('-')) {
          const sinAsignar = panel.querySelector('[data-deduccion="true"]');
          expect(getComputedStyle(sinAsignar).color).not.toBe(getComputedStyle(panel).color);
        }
        if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/sellout-reparto-${nombre}-${theme}.png` });
      });
    }
  }
});
