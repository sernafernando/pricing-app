/**
 * Sell in's Productos list -- real CSS, real Chromium: at desktop width the five columns fit the card without a
 * horizontal scroll, in light and dark; at phone width only the table scrolls, never the page.
 *
 *   pnpm exec vitest run --project=visual sellInProductosCosto
 *   VITE_SELLIN_PRODUCTOS_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellInProductosCosto   (also saves screenshots)
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import SellInProductosCosto from '../../components/sellIn/SellInProductosCosto';

const SHOTS_DIR = import.meta.env.VITE_SELLIN_PRODUCTOS_SHOTS_DIR;

const fila = (item_id, codigo, descripcion, modo, unidades, sell_in_unit, ultima_compra) => ({
  item_id,
  codigo,
  descripcion,
  modo,
  unidades,
  sell_in_unit,
  ultima_compra,
});

const PRODUCTOS = [
  fila(950, 'TPL-AX55', 'Router TP-Link Archer AX55', null, 200, '5472.000000', '2026-11-02'),
  fila(951, 'TPL-AX73', 'Router TP-Link Archer AX73', null, 84, '7120.500000', '2026-10-28'),
  fila(952, 'TPL-EAP225', 'Access Point TP-Link EAP225', 'ponderado', 312, '2150.330000', '2026-10-30'),
  fila(953, 'TPL-SG1016D', 'Switch TP-Link SG1016D', 'ultimo', 57, '3980.000000', '2026-10-21'),
  fila(954, 'TPL-PA7017', 'Powerline TP-Link TL-PA7017', null, 146, null, '2026-10-18'),
];

vi.mock('../../services/sellInAPI', () => ({
  sellInLotesAPI: { productos: vi.fn(() => Promise.resolve({ data: { productos: PRODUCTOS } })) },
}));

describe('SellInProductosCosto (visual)', () => {
  for (const theme of ['light', 'dark']) {
    it(`fits the card at desktop width, ${theme}`, async () => {
      await page.viewport(1280, 640);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      const screen = await render(
        <div data-testid="pagina" style={{ padding: 24 }}>
          <SellInProductosCosto onVer={() => {}} />
        </div>,
      );
      await expect.element(screen.getByRole('table')).toBeVisible();

      const tabla = screen.getByRole('table').element();
      expect(tabla.parentElement.scrollWidth).toBeLessThanOrEqual(tabla.parentElement.clientWidth + 1);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/productos-${theme}.png` });
    });
  }

  it('scrolls only the table at phone width', async () => {
    await page.viewport(390, 640);
    setTheme('light');
    const screen = await render(
      <div style={{ padding: 16 }}>
        <SellInProductosCosto onVer={() => {}} />
      </div>,
    );
    await expect.element(screen.getByRole('table')).toBeVisible();

    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390);
    const scroller = screen.getByRole('table').element().parentElement;
    expect(scroller.scrollWidth).toBeGreaterThan(scroller.clientWidth);
  });
});
