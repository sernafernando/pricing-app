/**
 * Nuevo tactical, sell out line with "monto total" (S1) in real Chromium: the split selector sits under what the line
 * includes, inside its column, the cap cells stay empty so the line keeps its columns under the heads.
 *
 *   VITE_TACTICAL_MONTO_TOTAL_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual tacticalMontoTotal
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import TacticalNuevo from '../../pages/TacticalNuevo';
import api, { productosAPI } from '../../services/api';
import { CATALOGO } from '../../components/tactical/tacticalFixtures';

const SHOTS_DIR = import.meta.env.VITE_TACTICAL_MONTO_TOTAL_SHOTS_DIR;

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
  api.get.mockImplementation((url, config) => {
    const words = config.params.q.toLowerCase().split(/\s+/);
    return Promise.resolve({
      data: CATALOGO.filter((p) => words.every((w) => `${p.codigo} ${p.descripcion}`.toLowerCase().includes(w))),
    });
  });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe.each(['light', 'dark'])('Nuevo tactical, sell out monto total, %s', (theme) => {
  it('the split selector fits under the products and the line keeps its columns', async () => {
    await page.viewport(1440, 900);
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
    await screen.getByLabelText('Nombre').fill('Bono notebooks HP noviembre');
    await screen.getByRole('button', { name: '+ Producto' }).click();
    await screen.getByLabelText('Buscar productos').fill('notebook hp');
    for (const nombre of ['Notebook HP 250RG10', 'Notebook HP 255r G10']) {
      await screen.getByRole('checkbox', { name: new RegExp(nombre) }).click();
    }
    await screen.getByRole('button', { name: 'Agregar a la línea' }).click();
    await screen.getByRole('button', { name: 'monto total' }).click();
    await screen.getByLabelText('Monto de la línea 1').fill('1.200');
    await screen.getByLabelText('Reparto del monto total, línea 1').selectOptions('unidades');
    await userEvent.keyboard('{Escape}');

    const linea1 = document.querySelector('[role="group"][aria-label="Línea 1"]');
    const head = [...linea1.parentElement.firstElementChild.children];
    const row = [...linea1.children];
    expect(row).toHaveLength(head.length);
    row.forEach((cell, i) => expect(Math.abs(cell.getBoundingClientRect().left - head[i].getBoundingClientRect().left)).toBeLessThanOrEqual(0.5));
    const selector = screen.getByLabelText('Reparto del monto total, línea 1').element().getBoundingClientRect();
    const incluye = row[2].getBoundingClientRect();
    expect(selector.left).toBeGreaterThanOrEqual(incluye.left - 0.5);
    expect(selector.right).toBeLessThanOrEqual(incluye.right + 0.5);
    expect(linea1.querySelector('[aria-label^="Tope de unidades"]')).toBeNull();

    linea1.scrollIntoView({ block: 'center' });
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tactical-sellout-monto-total-${theme}.png` });
  });
});
