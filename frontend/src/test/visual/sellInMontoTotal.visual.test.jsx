/**
 * Sell in monto total (S4) in real Chromium, light and dark: the Nuevo tactical sell in line with "monto total" (its
 * split selector under what the line includes, no cap cells), and a cost bonus by total amount in its panel (the
 * criterion, the ARS total and the stored shares table inside the panel width).
 *
 *   VITE_SELLIN_MONTO_TOTAL_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellInMontoTotal
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import TacticalNuevo from '../../pages/TacticalNuevo';
import SellInBonoPanel from '../../components/sellIn/SellInBonoPanel';
import api, { productosAPI } from '../../services/api';
import { sellInBonosAPI } from '../../services/sellInAPI';
import { CATALOGO } from '../../components/tactical/tacticalFixtures';
import { TACTICAL_REBATE } from '../../components/tacticals/tacticalsFixtures';
import { ALCANCE_VACIO, BONO_MONTO_TOTAL } from '../../components/sellIn/sellInFixtures';

const SHOTS_DIR = import.meta.env.VITE_SELLIN_MONTO_TOTAL_SHOTS_DIR;

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));
vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  productosAPI: { marcas: vi.fn(), categorias: vi.fn(), listar: vi.fn() },
}));
vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: { operaciones: vi.fn(), operacionProductos: vi.fn() },
  sellInBonosAPI: { detalle: vi.fn(), alcance: vi.fn(), crear: vi.fn(), editar: vi.fn(), anular: vi.fn() },
}));

beforeEach(() => {
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['HP', 'TP-Link'] } });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Monitores', 'Notebooks', 'Redes'] } });
  productosAPI.listar.mockResolvedValue({ data: { productos: [], total: 0, page: 1, page_size: 10 } });
  sellInBonosAPI.detalle.mockResolvedValue({ data: BONO_MONTO_TOTAL });
  sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE_VACIO });
  api.get.mockImplementation((url, config) => {
    if (url === '/tacticals/1') return Promise.resolve({ data: TOTAL_GUARDADO });
    if (!config?.params?.q) return Promise.resolve({ data: {} });
    const words = config.params.q.toLowerCase().split(/\s+/);
    return Promise.resolve({
      data: CATALOGO.filter((p) => words.every((w) => `${p.codigo} ${p.descripcion}`.toLowerCase().includes(w))),
    });
  });
});

// A sell in lump sum loaded before T5 PR A: a new one is no longer offered, an edit keeps it (L25).
const TOTAL_GUARDADO = {
  ...TACTICAL_REBATE,
  lineas: [
    {
      ...TACTICAL_REBATE.lineas[0],
      alcance: 'productos',
      marca: null,
      productos: CATALOGO.filter((p) => [103, 104].includes(p.item_id)),
      modo_monto: 'monto_total',
      valor: '1200000',
      tope_unidades: null,
      tope_monto: null,
      reparto_criterio: 'costo',
    },
  ],
};

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe.each(['light', 'dark'])('Sell in monto total, %s', (theme) => {
  it('a stored tactical sell in total line keeps its columns, with the split selector under the products', async () => {
    await page.viewport(1440, 900);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in/tactical/nuevo?tipo=sell_in&editar=1']}>
        <Shell>
          <Routes>
            <Route path="/sell-in/tactical/nuevo" element={<TacticalNuevo />} />
          </Routes>
        </Shell>
      </MemoryRouter>,
    );
    await expect.element(screen.getByRole('heading', { name: 'Editar tactical' })).toBeVisible();
    await expect.element(screen.getByLabelText('Reparto del monto total, línea 1')).toHaveValue('costo');
    await expect.element(screen.getByRole('button', { name: 'monto total' })).toHaveAttribute('aria-pressed', 'true');

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
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tactical-sellin-monto-total-${theme}.png` });
  });

  it('the bonus by total amount fits its criterion, total and shares in a panel', async () => {
    await page.viewport(1280, 1500); // tall enough for the shares table below the form, without scrolling the panel
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <div data-testid="panel" style={{ width: 480, background: 'var(--cf-bg-card)' }}>
        <SellInBonoPanel bonoId={21} marcas={['HP']} puedeGestionar onSaved={() => {}} onClose={() => {}} onVerCompra={() => {}} />
      </div>,
    );
    await expect.element(screen.getByRole('table', { name: 'Reparto del monto total' })).toBeVisible();
    await expect.element(screen.getByLabelText('Monto total (ARS)')).toHaveValue(1200000);
    await expect.element(screen.getByLabelText('Repartir el monto total')).toHaveValue('costo');

    const panel = document.querySelector('[data-testid="panel"]');
    const derecha = panel.getBoundingClientRect().right;
    for (const control of panel.querySelectorAll('select, input, td')) {
      expect(control.getBoundingClientRect().right).toBeLessThanOrEqual(derecha + 0.5);
    }
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/sellin-bono-monto-total-${theme}.png` });
  });
});
