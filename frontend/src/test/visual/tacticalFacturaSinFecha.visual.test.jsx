/**
 * Nuevo tactical, sell in with every line by invoice (tactical factura sin fecha S2c), in real Chromium: Vigencia says
 * «Por factura» in place of the date inputs, inside its card, and the sticky summary says it too.
 *
 * Screenshots are written only when `VITE_TACTICAL_SHOTS_DIR` is set (PR evidence).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import TacticalNuevo from '../../pages/TacticalNuevo';
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

beforeEach(() => {
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['HP', 'TP-Link'] } });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Monitores', 'Notebooks', 'Redes'] } });
  api.get.mockResolvedValue({ data: [] });
  sellInAPI.operaciones.mockResolvedValue({ data: { items: OPERACIONES } });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe.each([
  { width: 1440, height: 900, theme: 'light' },
  { width: 1440, height: 900, theme: 'dark' },
])('Nuevo tactical por factura at $width px, $theme', ({ width, height, theme }) => {
  it('shows Por factura in place of the dates', async () => {
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
    await screen.getByLabelText('Nombre').fill('Rebate TP-Link factura OC 12345');
    const linea = screen.getByRole('group', { name: 'Línea 1' });
    await linea.getByRole('button', { name: 'Factura', exact: true }).click();
    await linea.getByRole('button', { name: '+ Factura' }).click();
    await screen.getByLabelText('Buscar facturas').fill('0003');
    await screen.getByRole('checkbox', { name: /FC A 0003-00012345/ }).click();
    await screen.getByRole('button', { name: 'Agregar a la línea' }).click();
    await screen.getByLabelText('Monto de la línea 1').fill('850000');

    await expect.element(screen.getByText('Por factura', { exact: true }).first()).toBeVisible();
    expect(document.querySelector('#tactical-desde')).toBeNull();
    const card = screen.getByRole('heading', { name: 'Datos del tactical' }).element().closest('section').getBoundingClientRect();
    const nota = screen.getByText('Cada factura aplica hasta que se vendan sus unidades.').element().getBoundingClientRect();
    expect(nota.right).toBeLessThanOrEqual(card.right + 0.5);
    expect(document.querySelector('[data-testid="tactical-stickybar"]').textContent).toContain('Por factura');
    if (SHOTS_DIR) {
      window.scrollTo(0, 0);
      await page.screenshot({ path: `${SHOTS_DIR}/tactical-por-factura-${theme}-${width}.png` });
    }
  });
});
