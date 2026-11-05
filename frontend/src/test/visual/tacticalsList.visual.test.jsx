/**
 * Tactical list by brand (pending design handoffs/diseno-tactical/listado-tacticals-PENDIENTE.html): the Tacticals tab
 * with the design's three HP tacticals and the first one open on its lines. Real Chromium geometry: jsdom does no
 * layout.
 *
 *   VITE_SELLINOUT_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual tacticalsList   (also saves screenshots)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import SellIn from '../../pages/SellIn';
import { sellInAPI, sellInBonosAPI } from '../../services/sellInAPI';
import { BONOS_LISTA, LISTA, RESUMEN } from '../../components/sellIn/sellInFixtures';
import { sellOutAPI, sellOutProgramasAPI } from '../../services/sellOutAPI';
import { CAMPANAS_LISTA, PROGRAMAS_VACIO } from '../../components/sellOut/sellOutFixtures';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { TACTICAL_BPS, TACTICAL_REBATE, lineaDeProducto, pagina } from '../../components/tacticals/tacticalsFixtures';

const SHOTS_DIR = import.meta.env.VITE_SELLINOUT_SHOTS_DIR;

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  productosAPI: { marcas: vi.fn().mockResolvedValue({ data: { marcas: ['Acer', 'Asus', 'HP', 'Lenovo', 'TP-Link'] } }), listar: vi.fn() },
}));

vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: { listar: vi.fn(), resumen: vi.fn(), detalle: vi.fn() },
  sellInBonosAPI: { listar: vi.fn(), detalle: vi.fn() },
}));

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: { listar: vi.fn(), detalle: vi.fn(), grupos: vi.fn(), porPrograma: vi.fn() },
  sellOutProgramasAPI: { listar: vi.fn(), sugerencias: vi.fn() },
}));

vi.mock('../../services/tacticalsAPI', () => ({ tacticalsAPI: { listar: vi.fn(), editar: vi.fn(), anular: vi.fn() } }));

const TACTICALS = [
  {
    ...TACTICAL_BPS,
    lineas: [
      lineaDeProducto(11, 101, 'AIO-G2-R5', 'AIO HP G2 R5 16G 512 W11H', 220, 90, 58),
      lineaDeProducto(12, 102, 'AIO-PRO-S4', 'AIO PRO S4 G1 U5225T 24GB 512GB 24"', 170, 99, 41),
      lineaDeProducto(13, 103, 'NB-250RG10', 'Notebook HP 250RG10 5-120U', 100, 62, 62),
      lineaDeProducto(14, 104, 'NB-255R-G10', 'Notebook HP 255r G10 R3-7335u 8gb 512gb', 85, 106, 19),
      {
        ...TACTICAL_BPS.lineas[2],
        id: 15,
        productos: [...TACTICAL_BPS.lineas[2].productos, { item_id: 203, codigo: 'MON-P24', descripcion: 'Monitor P24 G5' }],
      },
    ],
  },
  {
    ...TACTICAL_BPS,
    id: 2,
    nombre: 'Monitores HP noviembre',
    referencia: null,
    fecha_hasta: '2026-11-15',
    lineas: [
      { ...lineaDeProducto(21, 201, 'MON-V24I', 'Monitor HP V24i G5', 12, 180, 172), tope_monto: '2160' },
      { ...lineaDeProducto(22, 202, 'MON-V27I', 'Monitor HP V27i G5', 12, 120, 108), tope_monto: '1440' },
    ],
  },
  TACTICAL_REBATE,
];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2026, 10, 12, 10));
  tacticalsAPI.listar.mockResolvedValue({ data: pagina(TACTICALS) });
  sellOutAPI.listar.mockResolvedValue({ data: CAMPANAS_LISTA });
  sellOutAPI.grupos.mockResolvedValue({ data: [] });
  sellOutProgramasAPI.listar.mockResolvedValue({ data: PROGRAMAS_VACIO });
  sellInAPI.listar.mockResolvedValue({ data: LISTA });
  sellInAPI.resumen.mockResolvedValue({ data: RESUMEN });
  sellInBonosAPI.listar.mockResolvedValue({ data: BONOS_LISTA });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

describe.each([
  { width: 1440, height: 1000, theme: 'light' },
  { width: 1440, height: 1000, theme: 'dark' },
])('Tacticals list at $width px, $theme', ({ width, height, theme }) => {
  it('lists the brand tacticals with the first one open on its lines', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in?tab=tacticals']}>
        <Shell>
          <SellIn />
        </Shell>
      </MemoryRouter>,
    );

    await screen.getByRole('button', { name: 'Ver las líneas de Tacticals BPS Noviembre Q1FY27' }).click();
    await expect.element(screen.getByText('Líneas del tactical (5)')).toBeVisible();
    await expect.element(screen.getByText('Tope alcanzado')).toBeVisible();
    await expect.element(screen.getByText('Vence en 3 días')).toBeVisible();
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tacticals-lista-${theme}-${width}.png` });
  });

  it("opens a row's actions menu whole, under its button, on the last row too", async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in?tab=tacticals']}>
        <Shell>
          <SellIn />
        </Shell>
      </MemoryRouter>,
    );

    await screen.getByRole('button', { name: 'Acciones de Rebate HP Q1FY27' }).click();
    const item = screen.getByRole('menuitem', { name: 'Renovar' });
    await expect.element(item).toBeVisible();
    const boton = document.querySelector('[aria-label="Acciones de Rebate HP Q1FY27"]').getBoundingClientRect();
    const menu = document.querySelector('[role="menu"]').getBoundingClientRect();
    expect(menu.top).toBeGreaterThanOrEqual(boton.bottom);
    expect(menu.right).toBeLessThanOrEqual(width + 0.5);
    // Nothing clips it (the table scrolls sideways): its bottom edge is still the menu's own.
    const abajo = document.elementFromPoint(menu.left + menu.width / 2, menu.bottom - 2);
    expect(abajo.closest('[role="menu"]')).not.toBeNull();
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tacticals-acciones-${theme}-${width}.png` });
  });

  it('opens the Editar dialog whole inside the window, with every line', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in?tab=tacticals']}>
        <Shell>
          <SellIn />
        </Shell>
      </MemoryRouter>,
    );

    await screen.getByRole('button', { name: `Acciones de ${TACTICAL_BPS.nombre}` }).click();
    await screen.getByRole('menuitem', { name: 'Editar' }).click();
    const dialogo = screen.getByRole('dialog', { name: `Editar ${TACTICAL_BPS.nombre}` });
    await expect.element(dialogo).toBeVisible();
    await expect.element(screen.getByLabelText('Tope de monto de la línea 2')).toBeVisible();
    const caja = document.querySelector('[role="dialog"]').getBoundingClientRect();
    expect(caja.top).toBeGreaterThanOrEqual(0);
    expect(caja.bottom).toBeLessThanOrEqual(height + 0.5);
    expect(caja.right).toBeLessThanOrEqual(width + 0.5);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tacticals-editar-${theme}-${width}.png` });
  });

  it('shows Nuevo tactical on the tab and opens the Anular dialog whole', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in?tab=tacticals']}>
        <Shell>
          <SellIn />
        </Shell>
      </MemoryRouter>,
    );

    await expect.element(screen.getByRole('button', { name: 'Nuevo tactical' })).toBeVisible();
    await screen.getByRole('button', { name: `Acciones de ${TACTICAL_BPS.nombre}` }).click();
    await screen.getByRole('menuitem', { name: 'Anular' }).click();
    await expect.element(screen.getByRole('dialog', { name: `¿Anular ${TACTICAL_BPS.nombre}?` })).toBeVisible();
    const caja = document.querySelector('[role="dialog"]').getBoundingClientRect();
    expect(caja.top).toBeGreaterThanOrEqual(0);
    expect(caja.bottom).toBeLessThanOrEqual(height + 0.5);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tacticals-anular-${theme}-${width}.png` });
  });
});
