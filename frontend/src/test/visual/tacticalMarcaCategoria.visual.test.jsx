/**
 * Nuevo tactical, a brand line narrowed to one category (SISO S3: "si quiero aplicar a los routers solo de tp-link")
 * in real Chromium: the line's category select sits under its brand select, same width, inside the line, and the help
 * below says what it covers.
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
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['HP', 'MERCUSYS', 'TP-Link'] } });
  productosAPI.categorias.mockImplementation((params) =>
    Promise.resolve({
      data: { categorias: params?.marca ? ['Redes', 'Routers', 'Switches'] : ['Monitores', 'Notebooks', 'Redes', 'Routers'] },
    }),
  );
  api.get.mockResolvedValue({ data: [] });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe.each([
  { width: 1440, height: 900, theme: 'light' },
  { width: 1440, height: 900, theme: 'dark' },
])('Nuevo tactical, brand line with a category at $width px, $theme', ({ width, height, theme }) => {
  it('shows the category select under the brand select, inside the line', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in/tactical/nuevo?tipo=sell_out']}>
        <Shell>
          <Routes>
            <Route path="/sell-in/tactical/nuevo" element={<TacticalNuevo />} />
          </Routes>
        </Shell>
      </MemoryRouter>,
    );
    await expect.element(screen.getByRole('heading', { name: 'Nuevo tactical' })).toBeVisible();
    await screen.getByLabelText('Nombre').fill('Rebate routers TP-Link');
    await screen.getByLabelText('Marca', { exact: true }).selectOptions('TP-Link');
    const linea = screen.getByRole('group', { name: 'Línea 1', exact: true });
    await linea.getByRole('button', { name: 'Marca', exact: true }).click();
    await linea.getByLabelText('Marca de la línea').selectOptions('TP-Link');
    const categoria = linea.getByLabelText('Categoría de la marca, línea 1');
    await expect.element(categoria.getByRole('option', { name: 'Routers' })).toBeInTheDocument();
    await categoria.selectOptions('Routers');
    await linea.getByLabelText('Monto de la línea 1').fill('1500');

    await expect.element(linea.getByText('Aplica a los productos de la marca en esa categoría.')).toBeVisible();
    const marca = linea.getByLabelText('Marca de la línea').element().getBoundingClientRect();
    const cat = categoria.element().getBoundingClientRect();
    const fila = linea.element().getBoundingClientRect();
    expect(cat.top).toBeGreaterThanOrEqual(marca.bottom);
    expect(Math.abs(cat.left - marca.left)).toBeLessThanOrEqual(0.5);
    expect(Math.abs(cat.width - marca.width)).toBeLessThanOrEqual(0.5);
    expect(cat.bottom).toBeLessThanOrEqual(fila.bottom);
    if (SHOTS_DIR) {
      await page.screenshot({ path: `${SHOTS_DIR}/tactical-marca-categoria-${theme}-${width}.png`, element: linea });
    }
  });
});
