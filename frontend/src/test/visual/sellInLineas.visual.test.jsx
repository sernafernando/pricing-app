/**
 * A sell-in purchase's line table (sell in incident 2026-11-24 S5, owner L35 "los costos en dólares mostrarlos en
 * dólares"), in the box the detail panel gives it at 1440 px with the sidebar open (524 px), light and dark:
 * - every amount of an ARS line (cost before, unit sell in, cost after, line total) has its USD equivalent below;
 * - the table fits the box with no horizontal scroll, with compra 31's widest amounts (1.021.608,48 total);
 * - the cost before is struck through, its USD line is not.
 * Real CSS in real Chromium.
 *
 *   VITE_SELL_IN_LINEAS_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellInLineas   (also saves screenshots)
 */

import { describe, it, expect } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import SellInLineas from '../../components/sellIn/SellInLineas';
import { COMPRA_DISTECNA } from '../../components/sellIn/sellInFixtures';

const SHOTS_DIR = import.meta.env.VITE_SELL_IN_LINEAS_SHOTS_DIR;
const CAJA = 524; // the detail panel's lines box at 1440 px with the sidebar open (captures of #2394)

/** Compra 31's widest amounts at its rate (prod 2026-11-24): a 633.437,80 unit cost and a 1.021.608,48 line total. */
const ANCHA = {
  id: 3101,
  item_id: 4726,
  codigo: '4726',
  descripcion: 'Producto de la compra 31',
  cantidad: 26,
  costo_base_unit: '633437.800000',
  monto_asignado: '1021608.48',
  descuento_unit: '39292.633800',
  costo_con_sell_in_unit: '594145.166200',
  porcentaje: '6.20',
};
const COMPRA = { ...COMPRA_DISTECNA, items: [...COMPRA_DISTECNA.items, ANCHA] };

describe.each(['light', 'dark'])('Sell in purchase lines at 1440 px, %s', (theme) => {
  it('shows each ARS amount with its USD equivalent below, inside the panel box', async () => {
    await page.viewport(1440, 900);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <div style={{ width: `${CAJA}px`, padding: '16px' }}>
        <SellInLineas compra={COMPRA} />
      </div>,
    );

    for (const usd of ['USD 17,00 a TC 1.580', 'USD 0,17 a TC 1.580', 'USD 16,83 a TC 1.580', 'USD 34,00 a TC 1.580']) {
      await expect.element(screen.getByText(usd)).toBeVisible();
    }
    await expect.element(screen.getByText('$ 1.021.608,48')).toBeVisible();

    const caja = screen.getByRole('table').element().parentElement;
    expect(caja.scrollWidth).toBeLessThanOrEqual(caja.clientWidth + 1);
    const total = screen.getByText('$ 1.021.608,48').element().getBoundingClientRect();
    expect(total.right).toBeLessThanOrEqual(caja.getBoundingClientRect().right + 1);

    const antes = screen.getByText('$ 26.856,90').element();
    expect(getComputedStyle(antes).textDecorationLine).toContain('line-through');
    const antesUsd = screen.getByText('USD 17,00 a TC 1.580').element();
    expect(getComputedStyle(antesUsd).textDecorationLine).toBe('none');

    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/sell-in-lineas-${theme}-1440.png` });
  });
});
