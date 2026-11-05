/**
 * "Renovar programa" (Stitch 26104b54) over the Programas section of the Sell out tab: the preview with its periods,
 * the campaigns to copy, the skipped ones, the left-out notice and the footer. Light, dark and high contrast. Real
 * Chromium geometry: jsdom does no layout.
 *
 *   VITE_SELLINOUT_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellOutRenovarPrograma   (also saves screenshots)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { contrastRatio, rgba, setTheme } from './visualHelpers';
import SellIn from '../../pages/SellIn';
import { sellInAPI, sellInBonosAPI } from '../../services/sellInAPI';
import { BONOS_LISTA, LISTA, RESUMEN } from '../../components/sellIn/sellInFixtures';
import { sellOutAPI, sellOutProgramasAPI } from '../../services/sellOutAPI';
import {
  CAMPANAS_DEL_PROGRAMA,
  CAMPANAS_LISTA,
  PROGRAMA_MARCA,
  PROGRAMAS_LISTA,
  RENOVACION_MARCA,
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
  sellOutProgramasAPI: {
    listar: vi.fn(),
    crear: vi.fn(),
    editar: vi.fn(),
    asignar: vi.fn(),
    sugerencias: vi.fn(),
    renovacion: vi.fn(),
    renovar: vi.fn(),
  },
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
  sellOutProgramasAPI.renovacion.mockResolvedValue({ data: RENOVACION_MARCA });
  sellInAPI.listar.mockResolvedValue({ data: LISTA });
  sellInAPI.resumen.mockResolvedValue({ data: RESUMEN });
  sellInBonosAPI.listar.mockResolvedValue({ data: BONOS_LISTA });
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

const box = (el) => el.getBoundingClientRect();
/** What paints behind `el`, as the eye sees it: translucent backgrounds (the dark theme's tone fills) composited over
 * the first opaque one beneath them. */
const fondo = (el) => {
  const capas = [];
  for (let n = el; n; n = n.parentElement) {
    const bg = getComputedStyle(n).backgroundColor;
    if (!bg || bg === 'transparent' || rgba(bg)[3] === 0) continue;
    capas.push(rgba(bg));
    if (rgba(bg)[3] === 1) break;
  }
  if (capas.length === 0 || capas[capas.length - 1][3] < 1) capas.push(rgba(getComputedStyle(document.body).backgroundColor));
  const [r, g, b] = capas.reduceRight((debajo, [cr, cg, cb, a]) => [
    cr * a + debajo[0] * (1 - a),
    cg * a + debajo[1] * (1 - a),
    cb * a + debajo[2] * (1 - a),
  ]);
  return `rgb(${r}, ${g}, ${b})`;
};

describe.each([
  { theme: 'light', highContrast: false },
  { theme: 'dark', highContrast: false },
  { theme: 'light', highContrast: true },
])('Renovar programa dialog, $theme, high contrast $highContrast', ({ theme, highContrast }) => {
  it('shows the preview centered, readable and without overflow', async () => {
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

    await screen.getByRole('row', { name: /MARCA PROG Programa de la marca/ }).getByRole('button', { name: 'Renovar programa' }).click();
    const dialogo = screen.getByRole('dialog', { name: 'Renovar programa «MARCA PROG»' });
    await expect.element(dialogo.getByRole('button', { name: 'Renovar 2 campañas' })).toBeVisible();

    // Centered, the md dialog width (672 px plus its border), inside the window.
    const modal = box(dialogo.element());
    expect(modal.width).toBeLessThanOrEqual(676);
    expect(Math.abs(modal.left + modal.width / 2 - width / 2)).toBeLessThan(2);
    expect(modal.bottom).toBeLessThanOrEqual(900);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);

    // The periods sit side by side: the target to the right of the source.
    const [origen, destino] = [...dialogo.getByRole('group', { name: 'Períodos' }).element().children].filter((n) => n.tagName === 'DIV');
    expect(box(destino).left).toBeGreaterThan(box(origen).right);

    // Each copy's source id sits at its row's right end, and every text reads at AA.
    const fila = dialogo.getByRole('list', { name: 'Se crearán 2' }).getByRole('listitem').first().element();
    const chip = dialogo.getByText('ID #11').element();
    expect(box(fila).right - box(chip).right).toBeLessThan(16);
    for (const texto of [
      chip,
      dialogo.getByText(/Quedan afuera de esta renovación/).element(),
      dialogo.getByText('Modelo C Q4 2026 — anulada, no se renueva').element(),
      dialogo.getByText(/Se crea todo o nada/).element(),
      dialogo.getByText('2 campañas listas para renovar').element(),
    ]) {
      expect(contrastRatio(getComputedStyle(texto).color, fondo(texto))).toBeGreaterThanOrEqual(4.5);
    }
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/renovar-programa-${modo}.png` });
    await dialogo.getByRole('button', { name: 'Cancelar' }).click();
    document.documentElement.classList.remove('high-contrast');
  });
});
