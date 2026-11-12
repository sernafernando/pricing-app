/**
 * Sell in factura pendiente S4, in real Chromium: the invoice picker offers an operation still without its supplier
 * invoice marked «Esperando factura», and a saved tactical waiting for it says so in its state and on its line; an
 * invoice total waiting for its invoice has no «Ver ventas» (sell in factura pendiente total).
 *
 * Screenshots are written only when `VITE_TACTICAL_SHOTS_DIR` is set (PR evidence).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import TacticalNuevo from '../../pages/TacticalNuevo';
import TacticalFila from '../../components/tacticals/TacticalFila';
import { TACTICAL_REBATE } from '../../components/tacticals/tacticalsFixtures';
import api, { productosAPI } from '../../services/api';
import { sellInAPI } from '../../services/sellInAPI';
import { OPERACIONES } from '../../components/tactical/tacticalFixtures';

const SHOTS_DIR = import.meta.env.VITE_TACTICAL_SHOTS_DIR;

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  productosAPI: { marcas: vi.fn(), categorias: vi.fn() },
}));

vi.mock('../../services/sellInAPI', () => ({
  sellInLotesAPI: { productos: vi.fn(() => new Promise(() => {})) },
  sellInAPI: { operaciones: vi.fn() },
}));

// The design's operations, the newest one still without its supplier invoice.
const PENDIENTE = { ...OPERACIONES[2], id: 9010, numero: 'OC 12410', numero_factura: null, fecha_factura: null };
const CON_FACTURA = OPERACIONES.map((o) => ({ ...o, fecha_factura: o.fecha }));

const ESPERANDO = {
  ...TACTICAL_REBATE,
  id: 7,
  nombre: 'Rebate TP-Link OC 12410',
  marca: 'TP-Link',
  marcas: ['TP-Link'],
  por_factura: true,
  esperando_factura: true,
  fecha_desde: '2026-11-12',
  fecha_hasta: '2026-11-12',
  lineas: [
    {
      ...TACTICAL_REBATE.lineas[0],
      id: 71,
      alcance: 'factura',
      marca: null,
      pedido_compra_id: 9010,
      pedido_numero: 'OC 12410',
      modo_monto: 'por_unidad',
      valor: '1500',
      unidades_usadas: 0,
      monto_usado: '0',
      esperando_factura: true,
    },
  ],
};

// A monto total line waiting for its invoice (follow-up of S4): stored apart, so it has no sales to open yet.
const TOTAL_ESPERANDO = {
  ...ESPERANDO,
  id: 8,
  nombre: 'Rebate TP-Link total OC 12410',
  lineas: [
    { ...ESPERANDO.lineas[0], id: 81, origen: 'sell_in_factura_pendiente', modo_monto: 'monto_total', valor: '850000' },
  ],
};

beforeEach(() => {
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['HP', 'TP-Link'] } });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Monitores', 'Notebooks', 'Redes'] } });
  api.get.mockResolvedValue({ data: [] });
  sellInAPI.operaciones.mockResolvedValue({ data: { items: [PENDIENTE, ...CON_FACTURA] } });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe.each([
  { width: 1440, height: 900, theme: 'light' },
  { width: 1440, height: 900, theme: 'dark' },
])('Sell in factura pendiente at $width px, $theme', ({ width, height, theme }) => {
  it('offers an operation without its invoice in the picker, marked Esperando factura', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in/tactical/nuevo?tipo=sell_in']}>
        <Shell>
          <Routes>
            <Route path="/sell-in/tactical/nuevo" element={<TacticalNuevo />} />
          </Routes>
        </Shell>
      </MemoryRouter>,
    );
    await expect.element(screen.getByRole('heading', { name: 'Nuevo tactical' })).toBeVisible();
    const linea = screen.getByRole('group', { name: 'Línea 1' });
    await linea.getByRole('button', { name: 'Factura', exact: true }).click();
    await linea.getByRole('button', { name: 'por unidad' }).click();
    await linea.getByRole('button', { name: '+ Factura' }).click();

    await expect.element(screen.getByText(/Operación OC 12410 · Esperando factura/)).toBeVisible();
    await expect.element(screen.getByRole('checkbox', { name: /OC 12410/ })).toBeEnabled();
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/factura-pendiente-picker-${theme}-${width}.png` });
  });

  it('shows a saved tactical waiting for its invoice', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <Shell>
        <table>
          <TacticalFila tactical={ESPERANDO} abierto onAlternar={() => {}} />
        </table>
      </Shell>,
    );

    await expect.element(screen.getByText('Esperando factura', { exact: true })).toBeVisible();
    await expect
      .element(screen.getByText('Esperando factura: se aplica cuando Compras vincule la factura del proveedor'))
      .toBeVisible();
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/factura-pendiente-lista-${theme}-${width}.png` });
  });

  it('shows an invoice total waiting for its invoice without Ver ventas', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <Shell>
        <table>
          <TacticalFila tactical={TOTAL_ESPERANDO} abierto onAlternar={() => {}} onVerLinea={() => {}} />
        </table>
      </Shell>,
    );

    await expect.element(screen.getByText('Esperando factura', { exact: true })).toBeVisible();
    await expect.element(screen.getByRole('columnheader', { name: 'Ventas' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Ver ventas de la línea 1' }).query()).toBeNull();
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/factura-pendiente-total-${theme}-${width}.png` });
  });
});
