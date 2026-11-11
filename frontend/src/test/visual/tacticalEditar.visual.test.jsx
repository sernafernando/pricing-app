/**
 * Editar tactical (SISO S8: "Que la edición abra nuevamente el modal de creación y poder editar directamente todo
 * ahí") in real Chromium: the Nuevo tactical screen titled "Editar tactical" with the tactical loaded, dates
 * included, and the confirmation that says what is recomputed and that a set al_cobro rate is discarded.
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
import { TACTICAL_BPS } from '../../components/tacticals/tacticalsFixtures';

const SHOTS_DIR = import.meta.env.VITE_TACTICAL_SHOTS_DIR;

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
  productosAPI: { marcas: vi.fn(), categorias: vi.fn() },
}));

vi.mock('../../services/sellInAPI', () => ({
  sellInLotesAPI: { productos: vi.fn(() => new Promise(() => {})) },
  sellInAPI: { operaciones: vi.fn() },
}));

const CON_TASA = { ...TACTICAL_BPS, lineas: TACTICAL_BPS.lineas.map((l) => ({ ...l, tc_al_cobro: '1450.000000' })) };

beforeEach(() => {
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['HP', 'TP-Link'] } });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Monitores', 'Notebooks'] } });
  api.get.mockImplementation((url) => Promise.resolve({ data: url === '/tacticals/1' ? CON_TASA : {} }));
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe.each([
  { width: 1440, height: 900, theme: 'light' },
  { width: 1440, height: 900, theme: 'dark' },
])('Editar tactical at $width px, $theme', ({ width, height, theme }) => {
  it('opens the creation screen loaded and confirms before replacing', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in/tactical/nuevo?tipo=sell_out&editar=1']}>
        <Shell>
          <Routes>
            <Route path="/sell-in/tactical/nuevo" element={<TacticalNuevo />} />
          </Routes>
        </Shell>
      </MemoryRouter>,
    );
    await expect.element(screen.getByRole('heading', { name: 'Editar tactical' })).toBeVisible();
    await expect.element(screen.getByLabelText('Desde')).toHaveValue('2026-11-01');
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tactical-editar-${theme}-${width}.png` });

    await screen.getByRole('group', { name: 'Tipo' }).getByRole('button', { name: 'Sell in' }).click();
    await screen.getByRole('button', { name: 'Guardar cambios' }).first().click();
    const dialogo = screen.getByRole('dialog', { name: '¿Guardar los cambios?' });
    await expect.element(dialogo.getByText(/Se descarta el tipo de cambio al cobro cargado/)).toBeVisible();
    const caja = dialogo.element().getBoundingClientRect();
    expect(caja.right).toBeLessThanOrEqual(width);
    expect(caja.bottom).toBeLessThanOrEqual(height);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tactical-editar-confirmar-${theme}-${width}.png` });
  });
});
