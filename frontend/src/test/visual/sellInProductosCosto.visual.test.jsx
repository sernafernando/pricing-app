/**
 * Sell in's Productos list -- real CSS, real Chromium: at desktop width the toolbar (search, Marca, Modo de costo,
 * Limpiar filtros and the default mode with "Cambiar") is one row and the columns with "Ver lotes" fit the card
 * without a horizontal scroll, in light and dark, and "Cambiar" opens the default-mode modal; at phone width only the
 * table scrolls, never the page.
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

const fila = (item_id, codigo, descripcion, modo, unidades, sell_in_unit, ultima_compra, marca = 'TP-LINK') => ({
  item_id,
  codigo,
  descripcion,
  marca,
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
  fila(955, 'MER-MS108', 'Switch Mercusys MS108', null, 90, '1210.000000', '2026-11-05', 'MERCUSYS'),
];

vi.mock('../../services/sellInAPI', () => ({
  sellInLotesAPI: {
    productos: vi.fn(() => Promise.resolve({ data: { productos: PRODUCTOS } })),
    modoPorDefecto: vi.fn(() => Promise.resolve({ data: { modo: 'fifo' } })),
    fijarModoPorDefecto: vi.fn((modo) => Promise.resolve({ data: { modo } })),
  },
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: () => true, rol: 'ADMIN' }),
}));

const box = (el) => el.getBoundingClientRect();

describe('SellInProductosCosto (visual)', () => {
  for (const theme of ['light', 'dark']) {
    it(`fits the toolbar in one row and the table in the card at desktop width, ${theme}`, async () => {
      await page.viewport(1366, 768);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      const screen = await render(
        <div data-testid="pagina" style={{ padding: 24 }}>
          <SellInProductosCosto onVer={() => {}} />
        </div>,
      );
      await expect.element(screen.getByRole('table')).toBeVisible();

      const cambiar = screen.getByRole('button', { name: 'Cambiar modo por defecto' });
      await expect.element(cambiar).toBeVisible();

      const tabla = screen.getByRole('table').element();
      expect(tabla.parentElement.scrollWidth).toBeLessThanOrEqual(tabla.parentElement.clientWidth + 1);
      // One toolbar row: the search and "Cambiar" share a bottom edge, and the toolbar sits above the table.
      const buscar = box(screen.getByPlaceholder('Buscar por código o descripción').element());
      expect(Math.abs(box(cambiar.element()).bottom - buscar.bottom)).toBeLessThan(2);
      expect(box(cambiar.element()).bottom).toBeLessThan(box(tabla).top);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1366);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/productos-${theme}-1366.png` });

      await cambiar.click();
      await expect.element(screen.getByRole('heading', { name: 'Modo por defecto' })).toBeVisible();
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/productos-modo-por-defecto-${theme}-1366.png` });
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
