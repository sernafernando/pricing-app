/**
 * The Sell out campaigns list after Stitch 5ee03d7d: the «ID #n» chip under each campaign's name, "Asignar ahora" on
 * the "Sin programa" group, and the bulk bar floating under the top bar while a long list scrolls. Light, dark and
 * high contrast. Real Chromium geometry: jsdom does no layout.
 *
 *   VITE_SELLINOUT_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellOutCampanasBulk   (also saves screenshots)
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
import { CAMPANA_MIGRADA, GRUPOS_POR_PROGRAMA, PROGRAMAS_LISTA, SUGERENCIAS } from '../../components/sellOut/sellOutFixtures';

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
  sellOutProgramasAPI: { listar: vi.fn(), crear: vi.fn(), editar: vi.fn(), asignar: vi.fn(), sugerencias: vi.fn() },
}));

const LARGA = Array.from({ length: 50 }, (_, i) => ({ ...CAMPANA_MIGRADA, id: 600 + i, nombre: `MODELO ${8100 + i}` }));

beforeEach(() => {
  sellOutAPI.listar.mockImplementation(async ({ page: p = 1, page_size: size = 10 }) => ({
    data: { items: LARGA.slice((p - 1) * size, p * size), total: LARGA.length, page: p, page_size: size },
  }));
  sellOutAPI.grupos.mockResolvedValue({ data: [] });
  sellOutAPI.porPrograma.mockResolvedValue({ data: GRUPOS_POR_PROGRAMA });
  sellOutProgramasAPI.listar.mockResolvedValue({ data: PROGRAMAS_LISTA });
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
])('Sell out campaigns: id chip, "Asignar ahora" and floating bar, $theme, high contrast $highContrast', ({ theme, highContrast }) => {
  const width = 1440;
  const preparar = async (url) => {
    await page.viewport(width, 900);
    setTheme(theme);
    document.documentElement.classList.toggle('high-contrast', highContrast);
    document.body.style.background = 'var(--cf-bg-app)';
    return render(
      <MemoryRouter initialEntries={[url]}>
        <Shell>
          <SellIn />
        </Shell>
      </MemoryRouter>,
    );
  };
  const modo = `${theme}${highContrast ? '-hc' : ''}`;

  it('"Sin programa" carries "Asignar ahora" at the row end and the expanded rows show their id chip', async () => {
    const screen = await preparar('/sell-in?tab=sell-out');
    const asignar = screen.getByRole('button', { name: 'Asignar ahora' });
    await expect.element(asignar).toBeVisible();
    await screen.getByRole('button', { name: /^Sin programa/ }).click();
    const chip = screen.getByText('ID #600');
    await expect.element(chip).toBeVisible();

    // The chip reads at AA on its own background; the button sits on the group row's right half.
    expect(contrastRatio(getComputedStyle(chip.element()).color, fondo(chip.element()))).toBeGreaterThanOrEqual(4.5);
    const fila = box(asignar.element().closest('tr'));
    expect(box(asignar.element()).left).toBeGreaterThan(fila.left + fila.width / 2);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/campanas-asignar-ahora-${modo}.png` });
    document.documentElement.classList.remove('high-contrast');
  });

  it('with a selection the bulk bar stays under the top bar while the list scrolls', async () => {
    const screen = await preparar('/sell-in?tab=sell-out&vista=lista');
    await page.viewport(width, 560); // shorter than the page, so it scrolls
    await screen.getByRole('checkbox', { name: 'Seleccionar MODELO 8100' }).click();
    await screen.getByRole('checkbox', { name: 'Seleccionar MODELO 8101' }).click();
    const contador = screen.getByText('2 seleccionadas');
    await expect.element(contador).toBeVisible();

    window.scrollTo(0, document.documentElement.scrollHeight);
    await new Promise((r) => requestAnimationFrame(r));
    expect(window.scrollY).toBeGreaterThan(0);
    const barra = box(screen.getByRole('button', { name: 'Anular seleccionados' }).element());
    const topbar = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--cf-topbar-height')) || 0;
    expect(barra.top).toBeGreaterThanOrEqual(topbar);
    expect(barra.bottom).toBeLessThanOrEqual(560);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/campanas-barra-flotante-${modo}.png` });
    window.scrollTo(0, 0);
    document.documentElement.classList.remove('high-contrast');
  });
});
