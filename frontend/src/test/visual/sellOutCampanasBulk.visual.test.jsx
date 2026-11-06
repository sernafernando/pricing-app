/**
 * The Sell out campaigns list after Stitch 5ee03d7d: the «ID #n» chip beside each campaign's name, "Asignar ahora" on
 * the "Sin programa" group, and the bulk bar floating at the bottom center of the window. Light, dark and
 * high contrast. Real Chromium geometry: jsdom does no layout.
 *
 *   VITE_SELLINOUT_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellOutCampanasBulk   (also saves screenshots)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { contrastRatio, setTheme, tokenColor } from './visualHelpers';
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
  // The Productos tab's list; never opened here.
  sellInLotesAPI: { productos: vi.fn(() => new Promise(() => {})) },
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

afterEach(() => {
  document.documentElement.classList.remove('high-contrast'); // even when an assertion failed first
  window.scrollTo(0, 0);
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

const box = (el) => el.getBoundingClientRect();
const fondo = (el) => {
  for (let n = el; n; n = n.parentElement) {
    const bg = getComputedStyle(n).backgroundColor;
    // A translucent tint (the bar's buttons) is not the backdrop: keep climbing to the opaque one.
    const translucido = /\/\s*0?\.\d+\)$|rgba\([^)]*,\s*0?\.\d+\)$|rgba\([^)]*,\s*0\)$/.test(bg);
    if (bg && bg !== 'transparent' && !translucido) return bg;
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

  it('"Sin programa" carries "Asignar ahora" right after its summary and the expanded rows show their id chip', async () => {
    const screen = await preparar('/sell-in?tab=sell-out');
    const asignar = screen.getByRole('button', { name: 'Asignar ahora' });
    await expect.element(asignar).toBeVisible();
    await screen.getByRole('button', { name: /^Sin programa/ }).click();
    const chip = screen.getByText('ID #600');
    await expect.element(chip).toBeVisible();

    // The chip reads at AA on its own background; the button sits on the group row's right half.
    expect(contrastRatio(getComputedStyle(chip.element()).color, fondo(chip.element()))).toBeGreaterThanOrEqual(4.5);
    // The group header reads as Stitch: bold name in the text color, then the summary, then the pill / "Asignar
    // ahora" right after it (not pushed to the row's far end).
    const grupo = screen.getByRole('button', { name: /^MARCA PROG/ }).element().closest('tr');
    const nombre = [...grupo.querySelectorAll('span')].find((n) => n.textContent === 'MARCA PROG');
    expect(Number(getComputedStyle(nombre).fontWeight)).toBeGreaterThanOrEqual(600);
    expect(getComputedStyle(nombre).color).toBe(tokenColor('--cf-text-primary'));
    const resumen = box(grupo.querySelector('[class*="resumen"]'));
    const pill = box(screen.getByText('2 activas').element());
    expect(pill.left - resumen.right).toBeLessThan(24);
    const sinResumen = box(asignar.element().closest('tr').querySelector('[class*="resumen"]'));
    expect(box(asignar.element()).left - sinResumen.right).toBeLessThan(120);
    // Its campaigns are indented under it, after a ↳ marker.
    const flecha = box(screen.getByText('MODELO 8100').element().closest('tr').querySelector('[aria-hidden="true"]'));
    const nombreHija = box(screen.getByText('MODELO 8100').element());
    expect(nombreHija.left).toBeGreaterThan(flecha.right);
    const cabecera = box([...document.querySelectorAll('th')].find((th) => th.textContent === 'Campaña'));
    expect(flecha.left - cabecera.left).toBeGreaterThanOrEqual(12); // nested: further in than the column's start
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/campanas-asignar-ahora-${modo}.png` });
  });

  it('with a selection the bulk bar floats at the bottom center of the window and covers no row at the end', async () => {
    const screen = await preparar('/sell-in?tab=sell-out&vista=lista');
    await page.viewport(width, 560); // shorter than the page, so it scrolls
    await screen.getByRole('checkbox', { name: 'Seleccionar MODELO 8100' }).click();
    await screen.getByRole('checkbox', { name: 'Seleccionar MODELO 8101' }).click();
    const barra = screen.getByRole('complementary', { name: 'Acciones masivas de campañas' });
    await expect.element(barra).toBeVisible();

    window.scrollTo(0, document.documentElement.scrollHeight);
    await new Promise((r) => requestAnimationFrame(r));
    expect(window.scrollY).toBeGreaterThan(0);
    const b = box(barra.element());
    expect(b.bottom).toBeLessThanOrEqual(560);
    expect(b.bottom).toBeGreaterThan(560 - 60); // at the bottom of the window
    expect(Math.abs((b.left + b.right) / 2 - width / 2)).toBeLessThan(2); // centered on the window
    // Scrolled to the end, the last row and the pagination stay above the bar.
    const ultima = box(screen.getByText('MODELO 8109').element().closest('tr'));
    expect(ultima.bottom).toBeLessThanOrEqual(b.top);
    expect(box(screen.getByRole('button', { name: 'Siguiente' }).element()).bottom).toBeLessThanOrEqual(b.top);
    // The bar's own labels read at AA on it ("Anular seleccionadas" is the app's danger button, painted by a gradient).
    const asignar = screen.getByRole('button', { name: 'Asignar a programa' }).element();
    expect(contrastRatio(getComputedStyle(asignar).color, fondo(asignar))).toBeGreaterThanOrEqual(4.5);
    const contador = screen.getByText('2 seleccionadas').element();
    expect(contrastRatio(getComputedStyle(contador).color, fondo(contador))).toBeGreaterThanOrEqual(4.5);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/campanas-barra-flotante-${modo}.png` });
  });
});
