/**
 * Sell in / Sell out — one page, two tabs under the title (Stitch
 * `01-sellin-lista-aplican`, `04-sellout-no-aplican`, dark `06`): the Sell in
 * tab holds the filters, the Aplicación and Tipo chips, the summary cards,
 * the purchases and the brand bonuses; the Sell out tab holds the campaigns.
 * Real Chromium geometry: jsdom does no layout.
 *
 *   VITE_SELLINOUT_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual sellInOutTabs   (also saves screenshots)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import SellIn from '../../pages/SellIn';
import { sellInAPI, sellInBonosAPI } from '../../services/sellInAPI';
import { BONO, BONOS_LISTA, LISTA, RESUMEN } from '../../components/sellIn/sellInFixtures';
import { sellOutAPI } from '../../services/sellOutAPI';
import { CAMPANAS_LISTA } from '../../components/sellOut/sellOutFixtures';

const SHOTS_DIR = import.meta.env.VITE_SELLINOUT_SHOTS_DIR;

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  productosAPI: { marcas: vi.fn().mockResolvedValue({ data: { marcas: ['TP-Link'] } }), listar: vi.fn() },
}));

vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: { listar: vi.fn(), resumen: vi.fn(), detalle: vi.fn() },
  sellInBonosAPI: { listar: vi.fn(), detalle: vi.fn() },
}));

vi.mock('../../services/sellOutAPI', () => ({ sellOutAPI: { listar: vi.fn(), detalle: vi.fn(), grupos: vi.fn() } }));

beforeEach(() => {
  sellOutAPI.listar.mockResolvedValue({ data: CAMPANAS_LISTA });
  sellOutAPI.grupos.mockResolvedValue({ data: [] });
  sellInAPI.listar.mockResolvedValue({ data: LISTA });
  sellInAPI.resumen.mockResolvedValue({ data: RESUMEN });
  sellInBonosAPI.listar.mockImplementation(async (params) =>
    params?.estado === 'activa' ? { data: { items: [BONO], total: 1, page: 1, page_size: 200 } } : { data: BONOS_LISTA },
  );
});

const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>{children}</div>
);

const box = (el) => el.getBoundingClientRect();

describe.each([
  { width: 1440, height: 900, theme: 'light' },
  { width: 1440, height: 900, theme: 'dark' },
  { width: 1920, height: 1080, theme: 'light' },
  { width: 1920, height: 1080, theme: 'dark' },
])('Sell in / Sell out at $width px, $theme', ({ width, height, theme }) => {
  it('puts the two tabs under the title, and the Sell in tab holds chips, cards, purchases and bonuses', async () => {
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <MemoryRouter initialEntries={['/sell-in']}>
        <Shell>
          <SellIn />
        </Shell>
      </MemoryRouter>,
    );
    await expect.element(screen.getByText('Bonificación Q4 switches')).toBeVisible();
    await expect.element(screen.getByText('Bono TP-Link USD 3/u')).toBeVisible();
    await expect.element(screen.getByText('Compras alcanzadas')).toBeVisible();

    const titulo = box(document.querySelector('h1'));
    const tabs = box(document.querySelector('[role="tablist"]'));
    const filtros = box(document.querySelector('[aria-label="Filtros"]'));
    const cards = box(document.querySelector('[aria-label="Resumen"]'));
    expect(tabs.top).toBeGreaterThanOrEqual(titulo.bottom - 0.5);
    expect(filtros.top).toBeGreaterThanOrEqual(tabs.bottom - 0.5);
    expect(cards.top).toBeGreaterThanOrEqual(filtros.bottom - 0.5);
    // Six summary cards in one row, as in the design.
    const tops = [...document.querySelectorAll('[aria-label="Resumen"] > div')].map((card) => Math.round(box(card).top));
    expect(tops).toHaveLength(6);
    expect(new Set(tops).size).toBe(1);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/sellinout-sell-in-${theme}-${width}.png` });

    await screen.getByRole('tab', { name: /Sell out/ }).click();
    await expect.element(screen.getByText('RB 8180')).toBeVisible();
    expect(document.querySelector('[aria-label="Resumen"]')).toBeNull();
    expect(screen.getByText('Bonificación Q4 switches').query()).toBeNull();
    const campanas = box(document.querySelector('#sell-out-panel'));
    expect(campanas.top).toBeGreaterThanOrEqual(box(document.querySelector('[role="tablist"]')).bottom - 0.5);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/sellinout-sell-out-${theme}-${width}.png` });
  });
});
