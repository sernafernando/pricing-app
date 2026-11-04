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

vi.mock('../../services/tacticalsAPI', () => ({ tacticalsAPI: { listar: vi.fn() } }));

const producto = (id, itemId, descripcion, valor, tope, usadas) => ({
  id,
  alcance: 'productos',
  productos: [{ item_id: itemId, descripcion }],
  modo_monto: 'por_unidad',
  valor: String(valor),
  tope_unidades: tope,
  tope_monto: null,
  unidades_usadas: usadas,
  monto_usado: String(valor * usadas),
});

const BASE = { marca: 'HP', moneda: 'USD', estado: 'activo', fecha_desde: '2026-11-01', referencia: null };
const TACTICALS = [
  {
    ...BASE,
    id: 1,
    tipo: 'sell_out',
    nombre: 'Tacticals BPS Noviembre Q1FY27',
    referencia: 'Q1 FY27 · BPS',
    fecha_hasta: '2026-11-30',
    lineas: [
      producto(11, 101, 'AIO HP G2 R5 16G 512 W11H', 220, 90, 58),
      producto(12, 102, 'AIO PRO S4 G1 U5225T 24GB 512GB 24"', 170, 99, 41),
      producto(13, 103, 'Notebook HP 250RG10 5-120U', 100, 62, 62),
      producto(14, 104, 'Notebook HP 255r G10 R3-7335u 8gb 512gb', 85, 106, 19),
      {
        id: 15,
        alcance: 'productos',
        productos: [
          { item_id: 201, descripcion: 'Monitor V24i G5' },
          { item_id: 202, descripcion: 'Monitor V27i G5' },
          { item_id: 203, descripcion: 'Monitor P24 G5' },
        ],
        modo_monto: 'por_unidad',
        valor: '12',
        tope_unidades: 300,
        tope_monto: '3000',
        unidades_usadas: 132,
        monto_usado: '1584',
      },
    ],
  },
  {
    ...BASE,
    id: 2,
    tipo: 'sell_out',
    nombre: 'Monitores HP noviembre',
    fecha_hasta: '2026-11-15',
    lineas: [
      { ...producto(21, 201, 'Monitor HP V24i G5', 12, 180, 172), tope_monto: '2160' },
      { ...producto(22, 202, 'Monitor HP V27i G5', 12, 120, 108), tope_monto: '1440' },
    ],
  },
  {
    ...BASE,
    id: 3,
    tipo: 'sell_in',
    nombre: 'Rebate HP Q1FY27',
    moneda: 'ARS',
    fecha_hasta: '2027-01-31',
    lineas: [
      {
        id: 31,
        alcance: 'marca',
        marca: 'HP',
        modo_monto: 'porcentaje',
        valor: '3.5',
        tope_unidades: null,
        tope_monto: null,
        unidades_usadas: null,
        monto_usado: '1240000',
      },
    ],
  },
];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2026, 10, 12, 10));
  tacticalsAPI.listar.mockResolvedValue({ data: { items: TACTICALS, total: TACTICALS.length } });
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
});
