/**
 * "Compras a revisar" (owner L29), the Sell in / Sell out page's tab of purchases held out of costo SI for a
 * suspicious price, with prod's item 23 / invoice 00128199 case. At 1440 px in light and dark:
 * - the table fits its card with no horizontal scroll, with the sidebar open (240 px);
 * - the suspicious price and the deviation chip are painted with the danger and warning tokens;
 * - "Aceptar" opens the confirmation.
 * Real CSS in real Chromium.
 *
 *   VITE_COMPRAS_REVISAR_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellInComprasRevisar   (also saves screenshots)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { tokenColor, setTheme } from './visualHelpers';
import SellIn from '../../pages/SellIn';
import { costoSiSospechasAPI } from '../../services/sellInAPI';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { pagina } from '../../components/tacticals/tacticalsFixtures';

const SHOTS_DIR = import.meta.env.VITE_COMPRAS_REVISAR_SHOTS_DIR;

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  productosAPI: { marcas: vi.fn().mockResolvedValue({ data: { marcas: ['TP-Link'] } }), listar: vi.fn() },
}));

vi.mock('../../services/sellInAPI', () => ({
  sellInLotesAPI: { productos: vi.fn(() => new Promise(() => {})) },
  sellInAPI: { listar: vi.fn(), resumen: vi.fn(), detalle: vi.fn() },
  sellInBonosAPI: { listar: vi.fn(), detalle: vi.fn() },
  costoSiSospechasAPI: { listar: vi.fn(), resumen: vi.fn(), aceptar: vi.fn(), excluir: vi.fn() },
}));

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: { listar: vi.fn(), detalle: vi.fn(), grupos: vi.fn(), consumos: vi.fn() },
}));

vi.mock('../../services/tacticalsAPI', () => ({ tacticalsAPI: { listar: vi.fn(), anular: vi.fn() } }));

/** Prod's case: item 23, invoice 00128199. */
const FILAS = [
  {
    id: 1,
    item_id: 23,
    codigo: '23',
    descripcion: 'EXTENSOR DE RANGO WIFI TP LINK TL-WA850RE 300MBPS',
    ct_transaction: 935025,
    factura: '00128199',
    fecha: '2026-10-27',
    cantidad: 312,
    precio: '0.00971',
    moneda: 'USD',
    precio_factura: '15.140000',
    moneda_factura: 'ARS',
    tipo_cambio: '1560.000000',
    referencia: '13.53550',
    fuente_ref: 'costo_si',
    ratio: '0.000717',
    estado: 'pendiente',
    revisor: null,
    revisado_at: null,
    nota: null,
  },
];

beforeEach(() => {
  tacticalsAPI.listar.mockResolvedValue({ data: pagina([]) });
  costoSiSospechasAPI.resumen.mockResolvedValue({ data: { pendientes: 1 } });
  costoSiSospechasAPI.listar.mockResolvedValue({ data: FILAS });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-expanded)' }}>{children}</div>
);

describe.each([
  { width: 1440, height: 900, theme: 'light' },
  { width: 1440, height: 900, theme: 'dark' },
])('Compras a revisar at $width px, $theme', ({ width, height, theme }) => {
  it('lists the item 23 invoice inside its card, in the theme colors, and opens the confirmation', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in?tab=revision']}>
        <Shell>
          <SellIn />
        </Shell>
      </MemoryRouter>,
    );

    await expect.element(screen.getByText('00128199')).toBeVisible();
    await expect.element(screen.getByRole('tab', { name: /Compras a revisar/ })).toHaveAttribute('aria-selected', 'true');
    const tabla = screen.getByRole('table', { name: 'Compras con precio sospechoso' }).element();
    expect(tabla.parentElement.scrollWidth).toBeLessThanOrEqual(tabla.parentElement.clientWidth + 1);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    const precio = screen.getByText('ARS 15,14').element();
    expect(getComputedStyle(precio).color).toBe(tokenColor('--cf-danger'));
    const desvio = screen.getByText(/1\/1\.395 de la referencia/).element();
    expect(getComputedStyle(desvio).color).toBe(tokenColor('--cf-warning'));
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/compras-revisar-${theme}-${width}.png` });

    await screen.getByRole('button', { name: /^Aceptar la compra de EXTENSOR/ }).click();
    await expect.element(screen.getByRole('heading', { name: 'Aceptar la compra' })).toBeVisible();
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/compras-revisar-aceptar-${theme}-${width}.png` });
  });
});
