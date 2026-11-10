/**
 * Nuevo tactical with several brands (S3, owner 2026-11-10: "selector multiple") in real Chromium: each brand is a
 * chip above the select, inside the brand field. A sell in tactical shows no store picker (stores are only for sell out).
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
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Monitores', 'Notebooks', 'Redes'] } });
  api.get.mockResolvedValue({ data: [] });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe.each([
  { width: 1440, height: 900, theme: 'light' },
  { width: 1440, height: 900, theme: 'dark' },
])('Nuevo tactical with several brands at $width px, $theme', ({ width, height, theme }) => {
  it('shows each brand as a chip inside its field', async () => {
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
    await screen.getByLabelText('Nombre').fill('Rebate redes noviembre');
    await screen.getByLabelText('Marca', { exact: true }).selectOptions('TP-Link');
    await screen.getByLabelText('Marca', { exact: true }).selectOptions('MERCUSYS');

    await expect.element(screen.getByRole('button', { name: 'Quitar TP-Link' })).toBeVisible();
    await expect.element(screen.getByRole('button', { name: 'Quitar MERCUSYS' })).toBeVisible();
    const campo = document.querySelector('#tactical-marca').closest('div').getBoundingClientRect();
    for (const marca of ['TP-Link', 'MERCUSYS']) {
      const chip = screen.getByRole('button', { name: `Quitar ${marca}` }).element().closest('span').getBoundingClientRect();
      expect(chip.left).toBeGreaterThanOrEqual(campo.left - 0.5);
      expect(chip.right).toBeLessThanOrEqual(campo.right + 0.5);
    }
    expect(document.querySelector('[data-testid="tactical-stickybar"]').textContent).toContain('TP-Link, MERCUSYS');
    if (SHOTS_DIR) {
      window.scrollTo(0, 0);
      await page.screenshot({ path: `${SHOTS_DIR}/tactical-varias-marcas-${theme}-${width}.png` });
    }
  });
});
