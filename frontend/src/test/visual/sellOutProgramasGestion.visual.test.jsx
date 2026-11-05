/**
 * The Programas section of the Sell out tab (Stitch 5ee03d7d plus program management): the programs table with one
 * program open, two of its campaigns checked and the "Quitar del programa | Mover a otro programa" bar, then the
 * "Nuevo programa" dialog. Light, dark and high contrast. Real Chromium geometry: jsdom does no layout.
 *
 *   VITE_SELLINOUT_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellOutProgramasGestion   (also saves screenshots)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { contrastRatio, setTheme } from './visualHelpers';
import SellIn from '../../pages/SellIn';
import { sellInAPI, sellInBonosAPI } from '../../services/sellInAPI';
import { BONOS_LISTA, LISTA, RESUMEN } from '../../components/sellIn/sellInFixtures';
import { sellOutAPI, sellOutProgramasAPI } from '../../services/sellOutAPI';
import {
  CAMPANAS_DEL_PROGRAMA,
  CAMPANAS_LISTA,
  PROGRAMA_MARCA,
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

// The page asks the Tacticals tab's count on load.
vi.mock('../../services/tacticalsAPI', () => ({
  tacticalsAPI: { listar: vi.fn().mockResolvedValue({ data: { total: 0, page: 1, page_size: 1, items: [] } }) },
}));

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: { listar: vi.fn(), detalle: vi.fn(), grupos: vi.fn(), porPrograma: vi.fn(), renovacion: vi.fn() },
  sellOutProgramasAPI: { listar: vi.fn(), crear: vi.fn(), editar: vi.fn(), asignar: vi.fn(), sugerencias: vi.fn() },
}));

const PROGRAMAS = {
  ...PROGRAMAS_LISTA,
  items: [
    { ...PROGRAMA_MARCA, descripcion: 'Programa de la marca por modelo' },
    ...PROGRAMAS_LISTA.items.slice(1),
    { ...PROGRAMA_MARCA, id: 9, nombre: 'MARCA Q1 2027', descripcion: null, campanas: 0, activas: 0, nombres: 0, desde: null, hasta: null },
  ],
};

beforeEach(() => {
  sellOutAPI.listar.mockImplementation(async (p) => ({ data: p.programa_id === 7 ? CAMPANAS_DEL_PROGRAMA : CAMPANAS_LISTA }));
  sellOutAPI.grupos.mockResolvedValue({ data: [] });
  sellOutProgramasAPI.listar.mockResolvedValue({ data: PROGRAMAS });
  sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
  sellInAPI.listar.mockResolvedValue({ data: LISTA });
  sellInAPI.resumen.mockResolvedValue({ data: RESUMEN });
  sellInBonosAPI.listar.mockResolvedValue({ data: BONOS_LISTA });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

const box = (el) => el.getBoundingClientRect();
const fondo = (el) => {
  for (let n = el; n; n = n.parentElement) {
    const bg = getComputedStyle(n).backgroundColor;
    if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return bg;
  }
  return getComputedStyle(document.body).backgroundColor;
};

describe.each([
  { theme: 'light', highContrast: false },
  { theme: 'dark', highContrast: false },
  { theme: 'light', highContrast: true },
])('Sell out Programas section, $theme, high contrast $highContrast', ({ theme, highContrast }) => {
  it('lists the programs, opens one with the selection bar and shows the new-program dialog', async () => {
    const width = 1440;
    await page.viewport(width, 900);
    setTheme(theme);
    document.documentElement.classList.toggle('high-contrast', highContrast);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in?tab=sell-out&seccion=programas']}>
        <Shell>
          <SellIn />
        </Shell>
      </MemoryRouter>,
    );
    const modo = `${theme}${highContrast ? '-hc' : ''}`;

    await screen.getByRole('button', { name: 'Ver campañas de MARCA PROG' }).click();
    await screen.getByRole('checkbox', { name: 'Seleccionar MARCA PROG 3.0' }).click();
    await screen.getByRole('checkbox', { name: 'Seleccionar MARCA PROGRAM1' }).click();
    await expect.element(screen.getByRole('button', { name: 'Quitar del programa' })).toBeVisible();
    await expect.element(screen.getByText(/Programa es el nivel superior/)).toBeVisible();

    // The hierarchy line reads at AA on its background; nothing overflows sideways.
    const jerarquia = screen.getByText(/Programa es el nivel superior/).element();
    expect(contrastRatio(getComputedStyle(jerarquia).color, fondo(jerarquia))).toBeGreaterThanOrEqual(4.5);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    // The "Nuevo programa" button sits on the header's right, level with the title.
    const titulo = box(screen.getByRole('heading', { name: 'Programas' }).element());
    const nuevo = box(screen.getByRole('button', { name: 'Nuevo programa' }).element());
    expect(nuevo.left).toBeGreaterThan(titulo.right);
    expect(nuevo.top).toBeLessThan(titulo.bottom);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/programas-gestion-${modo}.png` });

    await screen.getByRole('button', { name: 'Nuevo programa' }).click();
    const dialogo = screen.getByRole('dialog', { name: 'Nuevo programa' });
    await dialogo.getByLabelText('Nombre').fill('MARCA Q2 2027');
    const modal = box(dialogo.element());
    expect(modal.left).toBeGreaterThan(0);
    expect(modal.right).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/programas-gestion-nuevo-${modo}.png` });
    await dialogo.getByRole('button', { name: 'Cancelar' }).click();
    document.documentElement.classList.remove('high-contrast');
  });
});
