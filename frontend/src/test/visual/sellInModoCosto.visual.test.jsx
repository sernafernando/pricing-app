/**
 * The cost-mode panel inside the sell-in lot viewer -- real CSS, real Chromium: in a product-panel-width column the
 * mode switch, the date, the preview (with its before/after table and the last-price warning) and the history fit
 * without overflowing, in light, dark and high contrast; the admin's default-mode modal fits a phone-width screen.
 *
 *   pnpm exec vitest run --project=visual sellInModoCosto
 *   VITE_SELLIN_MODO_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellInModoCosto   (also saves screenshots)
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import SellInLotes from '../../components/sellIn/SellInLotes';

const SHOTS_DIR = import.meta.env.VITE_SELLIN_MODO_SHOTS_DIR;

const LOTES = {
  item_id: 950,
  lotes: [
    { numero: 1, compra_item_id: 501, compra_id: 41, proveedor: 'TP-Link Argentina', facturas: ['A-0003-00012345'], moneda: 'ARS', fecha_desde: '2026-10-15', cantidad: 40, consumidas: 0, restantes: 40, descuento_unit: '5472.000000', estado: 'vigente' },
    { numero: 2, compra_item_id: 502, compra_id: 42, proveedor: 'TP-Link Argentina', facturas: ['A-0003-00012400'], moneda: 'ARS', fecha_desde: '2026-10-28', cantidad: 100, consumidas: 0, restantes: 100, descuento_unit: '5346.000000', estado: 'en_cola' },
    { numero: 3, compra_item_id: 503, compra_id: 43, proveedor: 'TP-Link Argentina', facturas: ['A-0003-00012433'], moneda: 'ARS', fecha_desde: '2026-11-02', cantidad: 60, consumidas: 0, restantes: 60, descuento_unit: '4980.000000', estado: 'en_cola' },
  ],
  proxima: { numero: 1, compra_item_id: 501, descuento_unit: '5472.000000', restantes: 40, siguiente: { numero: 2, descuento_unit: '5346.000000', fecha_desde: '2026-10-28', estado: 'en_cola' } },
  bono_costo: null,
  compra_visible: true,
};

const fila = (id, modo, desde, created) => ({ id, modo, desde, cantidad: null, costo_unit: null, costo_base_unit: null, origen: 'visor', compra_id: null, usuario_id: 1, usuario_nombre: 'Fernando', created_at: created });

vi.mock('../../services/sellInAPI', () => ({
  sellInLotesAPI: {
    lotes: vi.fn(() => Promise.resolve({ data: LOTES })),
    consumos: vi.fn(() => Promise.resolve({ data: { items: [], total: 0, page: 1, page_size: 20 } })),
    modos: vi.fn(() =>
      Promise.resolve({
        data: {
          item_id: 950,
          vigente: fila(7, 'ultimo', '2026-11-01', '2026-11-02T10:00:00'),
          historial: [fila(7, 'ultimo', '2026-11-01', '2026-11-02T10:00:00'), fila(6, 'fifo', '2026-10-28', '2026-10-28T09:00:00')],
        },
      }),
    ),
    vistaPrevia: vi.fn(() =>
      Promise.resolve({
        data: { ventas_cambian: 6, diferencia_ars: '-18240.50', unidades_restantes: 200, descuento_unit: '5280.400000', sin_asignar_antes: '0.00', sin_asignar_despues: '200.00', huella: 'a'.repeat(64) },
      }),
    ),
    confirmarModo: vi.fn(),
    modoPorDefecto: vi.fn(() => Promise.resolve({ data: { modo: 'ponderado' } })),
    fijarModoPorDefecto: vi.fn(),
  },
}));
vi.mock('../../contexts/PermisosContext', () => ({ usePermisos: () => ({ tienePermiso: () => true, rol: 'ADMIN' }) }));

afterEach(() => document.documentElement.classList.remove('high-contrast'));

describe('SellInModoCosto in the lot viewer (visual)', () => {
  for (const theme of ['light', 'dark']) {
    for (const highContrast of [false, true]) {
      it(`fits a 560px panel with the preview open, ${theme}${highContrast ? ', high contrast' : ''}`, async () => {
        await page.viewport(1280, 1400);
        setTheme(theme);
        document.documentElement.classList.toggle('high-contrast', highContrast);
        document.body.style.background = 'var(--cf-bg-app)';
        const screen = await render(
          <div data-testid="panel" style={{ width: 560, padding: 16, background: 'var(--cf-bg-card)' }}>
            <SellInLotes productItemId={950} />
          </div>,
        );
        await userEvent.click(screen.getByRole('button', { name: 'Ponderado (PPP)' }));
        await userEvent.click(screen.getByRole('button', { name: 'Ver cómo queda' }));
        await expect.element(screen.getByRole('region', { name: 'Así queda' })).toBeVisible();

        const panel = document.querySelector('[data-testid="panel"]');
        expect(panel.scrollWidth).toBeLessThanOrEqual(panel.clientWidth + 1);
        const modos = screen.getByRole('group', { name: 'Cambiar a' }).element().getBoundingClientRect();
        expect(modos.right).toBeLessThanOrEqual(panel.getBoundingClientRect().right);
        if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/modo-costo-${theme}${highContrast ? '-hc' : ''}.png` });
      });
    }
  }

  for (const theme of ['light', 'dark']) {
    it(`the admin's default-mode modal fits a phone-width screen, ${theme}`, async () => {
      await page.viewport(390, 844);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      const screen = await render(
        <div style={{ padding: 16, background: 'var(--cf-bg-card)' }}>
          <SellInLotes productItemId={950} />
        </div>,
      );
      await userEvent.click(screen.getByRole('button', { name: 'Modo por defecto' }));
      const grupo = page.getByRole('group', { name: 'Modo por defecto' });
      await expect.element(grupo).toBeVisible();
      await userEvent.click(grupo.getByRole('button', { name: 'Último precio' }));
      const modal = document.querySelector('.modal-tesla');
      expect(modal.scrollWidth).toBeLessThanOrEqual(modal.clientWidth + 1);
      expect(modal.getBoundingClientRect().right).toBeLessThanOrEqual(390);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/modo-por-defecto-${theme}.png` });
    });
  }
});
