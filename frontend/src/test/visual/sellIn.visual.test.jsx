/**
 * Sell in — the create panel sits BESIDE the list, never over it (DESIGN.md:
 * "the page stays visible on the left, no modal"), in both themes, at a
 * laptop width and a wide one. Real Chromium geometry: jsdom does no layout.
 * The picker's products card (resting on an operation) stays inside the viewport.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import SellIn from '../../pages/SellIn';
import { sellInAPI, sellInBonosAPI } from '../../services/sellInAPI';
import { BONOS_LISTA, LISTA, PRODUCTOS_OPERACION, RESUMEN, operacionesFake } from '../../components/sellIn/sellInFixtures';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  productosAPI: { marcas: vi.fn().mockResolvedValue({ data: { marcas: ['TP-Link'] } }), listar: vi.fn() },
}));

vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: {
    listar: vi.fn(),
    resumen: vi.fn(),
    detalle: vi.fn(),
    preview: vi.fn(),
    crear: vi.fn(),
    anular: vi.fn(),
    proveedores: vi.fn(),
    operaciones: vi.fn(),
    operacionProductos: vi.fn(),
  },
  sellInBonosAPI: { listar: vi.fn(), detalle: vi.fn(), crear: vi.fn(), editar: vi.fn(), anular: vi.fn() },
}));

beforeEach(() => {
  sellInAPI.listar.mockResolvedValue({ data: LISTA });
  sellInAPI.resumen.mockResolvedValue({ data: RESUMEN });
  sellInBonosAPI.listar.mockResolvedValue({ data: BONOS_LISTA });
  sellInAPI.operaciones.mockImplementation(operacionesFake);
  sellInAPI.operacionProductos.mockResolvedValue({ data: PRODUCTOS_OPERACION });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe.each([
  { width: 1366, height: 768, theme: 'light' },
  { width: 1920, height: 1080, theme: 'dark' },
])('Sell in at $width px, $theme', ({ width, height, theme }) => {
  it('opens the create panel as a column beside the table, without covering it', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in']}>
        <Shell>
          <SellIn />
        </Shell>
      </MemoryRouter>,
    );
    await expect.element(screen.getByText('Bonificación Q4 switches')).toBeVisible();
    await screen.getByRole('button', { name: /Nuevo sell in/ }).click();
    await expect.element(screen.getByRole('heading', { name: 'Nuevo sell in · Por compra' })).toBeVisible();

    const aside = document.querySelector('[data-split-panel]');
    const table = document.querySelector('table');
    const panelBox = aside.getBoundingClientRect();
    const tableBox = table.parentElement.getBoundingClientRect();
    expect(panelBox.left).toBeGreaterThanOrEqual(tableBox.right - 0.5);
    expect(panelBox.right).toBeLessThanOrEqual(width + 0.5);
    expect(document.querySelector('[role="dialog"], [aria-modal="true"]')).toBeNull();

    await screen.getByLabelText('Pedido de compra (N°)').click();
    await screen.getByRole('option', { name: /N° 16/ }).hover();
    await expect.element(screen.getByRole('row', { name: /SW-8/ })).toBeVisible();
    const card = document.querySelector('[role="tooltip"]').getBoundingClientRect();
    expect(card.left).toBeGreaterThanOrEqual(0);
    expect(card.top).toBeGreaterThanOrEqual(0);
    expect(card.right).toBeLessThanOrEqual(width + 0.5);
    expect(card.bottom).toBeLessThanOrEqual(height + 0.5);
    const lista = document.querySelector('[role="listbox"]').getBoundingClientRect();
    expect(card.right).toBeLessThanOrEqual(lista.left + 0.5); // beside the options: the picker stays usable
  });
});
