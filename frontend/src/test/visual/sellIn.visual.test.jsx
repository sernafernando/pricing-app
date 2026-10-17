/**
 * Sell in — the create panel sits BESIDE the list, never over it (DESIGN.md:
 * "the page stays visible on the left, no modal"), in both themes, at a
 * laptop width and a wide one. Real Chromium geometry: jsdom does no layout.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import SellIn from '../../pages/SellIn';
import { sellInAPI } from '../../services/sellInAPI';
import { LISTA, RESUMEN } from '../../components/sellIn/sellInFixtures';

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
  },
}));

beforeEach(() => {
  sellInAPI.listar.mockResolvedValue({ data: LISTA });
  sellInAPI.resumen.mockResolvedValue({ data: RESUMEN });
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
  });
});
