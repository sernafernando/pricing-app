/**
 * Sell out programs (campanas-sistema slice E, Stitch `programas/lista`, `modal`, `drawer`): the list grouped by
 * program with one group open, rows checked and the bulk bar; the "Asignar a programa" dialog with the API's
 * archived-program refusal; and the "Sugerencias de programa" drawer. Real Chromium geometry: jsdom does no layout.
 *
 *   VITE_SELLINOUT_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellOutProgramas   (also saves screenshots)
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
import {
  CAMPANAS_DEL_PROGRAMA,
  CAMPANAS_LISTA,
  GRUPOS_POR_PROGRAMA,
  PROGRAMAS_LISTA,
  SUGERENCIAS,
} from '../../components/sellOut/sellOutFixtures';

const SHOTS_DIR = import.meta.env.VITE_SELLINOUT_SHOTS_DIR;

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  productosAPI: { marcas: vi.fn().mockResolvedValue({ data: { marcas: ['MARCA'] } }), listar: vi.fn() },
}));

vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: { listar: vi.fn(), resumen: vi.fn(), detalle: vi.fn() },
  sellInBonosAPI: { listar: vi.fn(), detalle: vi.fn() },
}));

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: { listar: vi.fn(), detalle: vi.fn(), grupos: vi.fn(), porPrograma: vi.fn(), renovacion: vi.fn() },
  sellOutProgramasAPI: { listar: vi.fn(), crear: vi.fn(), asignar: vi.fn(), sugerencias: vi.fn() },
}));

beforeEach(() => {
  sellOutAPI.listar.mockImplementation(async (p) => ({ data: p.programa_id === 7 ? CAMPANAS_DEL_PROGRAMA : CAMPANAS_LISTA }));
  sellOutAPI.grupos.mockResolvedValue({ data: [] });
  sellOutAPI.porPrograma.mockResolvedValue({ data: GRUPOS_POR_PROGRAMA });
  sellOutProgramasAPI.listar.mockResolvedValue({ data: PROGRAMAS_LISTA });
  sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
  sellOutProgramasAPI.asignar.mockRejectedValue({
    response: { status: 422, data: { error: { message: 'El programa «MARCA PROG» está archivado.' } } },
  });
  sellInAPI.listar.mockResolvedValue({ data: LISTA });
  sellInAPI.resumen.mockResolvedValue({ data: RESUMEN });
  sellInBonosAPI.listar.mockResolvedValue({ data: BONOS_LISTA });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

const box = (el) => el.getBoundingClientRect();

describe.each([
  { width: 1440, height: 900, theme: 'light' },
  { width: 1440, height: 900, theme: 'dark' },
])('Sell out programs at $width px, $theme', ({ width, height, theme }) => {
  it('groups the list by program, assigns in bulk and shows the suggestions drawer', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in?tab=sell-out']}>
        <Shell>
          <SellIn />
        </Shell>
      </MemoryRouter>,
    );

    // The grouped list: one group open, two rows checked, the bulk bar with "Asignar a programa".
    await screen.getByRole('button', { name: /^MARCA PROG/ }).click();
    await expect.element(screen.getByText('MARCA PROG 3.0')).toBeVisible();
    await screen.getByRole('checkbox', { name: 'Seleccionar MARCA PROG 3.0' }).click();
    await screen.getByRole('checkbox', { name: 'Seleccionar MARCA PROGRAM1' }).click();
    await expect.element(screen.getByText('2 seleccionadas')).toBeVisible();
    await expect.element(screen.getByText('2 sugerencias de programa: campañas sin programa con las mismas fechas')).toBeVisible();
    const filtros = box(document.querySelector('[aria-label="Filtros de campañas"]'));
    const tabla = box(document.querySelector('#sell-out-panel table'));
    expect(tabla.top).toBeGreaterThanOrEqual(filtros.bottom - 0.5);
    // The group row's pill sits at the row's right edge, as in the design.
    const grupo = document.querySelector('#sell-out-panel tbody tr');
    const pill = [...grupo.querySelectorAll('span')].find((s) => s.textContent === '2 activas');
    expect(box(grupo).right - box(pill).right).toBeLessThan(40);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/programas-lista-${theme}-${width}.png` });

    // The dialog, with the API's refusal inline.
    await screen.getByRole('button', { name: 'Asignar a programa' }).click();
    const dialogo = screen.getByRole('dialog', { name: 'Asignar a programa (2 campañas)' });
    await dialogo.getByLabelText('Programa', { exact: true }).selectOptions('7');
    await dialogo.getByRole('button', { name: 'Asignar' }).click();
    await expect.element(dialogo.getByText('El programa «MARCA PROG» está archivado.')).toBeVisible();
    const modal = box(dialogo.element());
    expect(modal.left).toBeGreaterThan(0);
    expect(modal.right).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/programas-modal-${theme}-${width}.png` });
    await dialogo.getByRole('button', { name: 'Cancelar' }).click();

    // The suggestions drawer, docked right, first card's campaigns open.
    await screen.getByRole('button', { name: 'Ver sugerencias' }).click();
    const drawer = screen.getByRole('dialog', { name: 'Sugerencias de programa' });
    await drawer.getByRole('button', { name: 'Ver campañas' }).first().click();
    await expect.element(drawer.getByText('MARCA PROGRAM1 (×2)')).toBeVisible();
    const panel = box(drawer.element());
    expect(Math.abs(panel.right - width)).toBeLessThan(1);
    expect(panel.top).toBeLessThan(1);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/programas-drawer-${theme}-${width}.png` });
  });
});
