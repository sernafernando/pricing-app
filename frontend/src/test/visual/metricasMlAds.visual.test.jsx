/**
 * Métricas ML ads toggle — the four states of the approved design (off,
 * "publicaciones", "todo", "todo" applied as "publicaciones" under filters)
 * in real Chromium, light and dark, at the 1366 width operators use.
 *
 * Asserts what the mocks promise: the banner and the adjusted cards read whole
 * (no wrapped money), nothing pokes out of the page, and the notice + chip
 * only exist in the downgraded state. Screenshots only when
 * `VITE_METRICAS_SHOTS_DIR` is set (a DEV aid, never a committed baseline).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { contrastRatio, setTheme } from './visualHelpers';
import MetricasML from '../../pages/MetricasML';
import api from '../../services/api';
import { BOARD_RESPONSE } from './metricasMlFixtures';
import { ADS_KPIS, ADS_WATERFALL_TODO } from '../../components/metricasMl/adsFixtures';

vi.mock('react-router-dom', async () => ({
  // The page keeps its filters in the URL (U1): an in-memory query, empty at the start.
  useSearchParams: (await import('./searchParamsMock')).useSearchParams,
  Link: ({ to, children, ...rest }) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  productosAPI: {
    marcas: vi.fn(() => Promise.resolve({ data: { marcas: [] } })),
    subcategorias: vi.fn(() => Promise.resolve({ data: { categorias: [] } })),
    obtenerMarcasPorPMs: vi.fn(() => Promise.resolve({ data: { marcas: [] } })),
    obtenerSubcategoriasPorPMs: vi.fn(() => Promise.resolve({ data: { subcategorias: [] } })),
  },
  authAPI: { login: vi.fn(), me: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const SHOTS_DIR = import.meta.env.VITE_METRICAS_SHOTS_DIR;

const UNATTRIBUTED = {
  sin_producto_cost: 412380,
  account_level: { display: { cost_api: 1512500, cost_net: 1250000, subtracted: true }, brand: { cost: 380500, subtracted: true } },
};

// What the API answers per position: `todo` asked but only `mla` applicable is the filtered case.
const ADS_BY_POSITION = {
  mla: ADS_KPIS,
  todo: {
    ...ADS_KPIS,
    requested: 'todo',
    applied: 'todo',
    contribution: 1265000,
    no_campaign: 84300,
    subtracted_total: 18294119.51,
    unattributed: UNATTRIBUTED,
    waterfall: ADS_WATERFALL_TODO,
  },
  todo_filtered: {
    ...ADS_KPIS,
    requested: 'todo',
    applied: 'mla',
    subtracted_total: 2192372.86,
    waterfall: { ...ADS_KPIS.waterfall, product_ads_publications: 2192372.86, product_ads_net: 2192372.86, total: 2192372.86 },
  },
};

let filteredTodo = false;
const answer = (position) => {
  if (!position) return BOARD_RESPONSE;
  const ads = position === 'todo' && filteredTodo ? ADS_BY_POSITION.todo_filtered : ADS_BY_POSITION[position];
  const rows = BOARD_RESPONSE.rows.map((row) => ({ ...row, ads: { cost: 410200 } }));
  // Unfiltered, the API also sends the "sin producto" row.
  if (ads.unattributed) rows.push({ ...rows[0], key: 'p-0', product_item_id: 0, title: 'Sin producto', units: 0, gross: 0, ads: { cost: 412380 } });
  return { ...BOARD_RESPONSE, kpis: { ...BOARD_RESPONSE.kpis, ads }, rows };
};

beforeEach(() => {
  filteredTodo = false;
  api.get.mockReset();
  api.get.mockImplementation((url, config) => {
    if (url === '/ml-metricas/board') return Promise.resolve({ data: answer(config?.params?.publicidad) });
    return Promise.resolve({ data: {} });
  });
});

const shot = async (name) => {
  if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/${name}.png` });
};

// The whole card, which runs past the 900 px viewport: the PR compares it with Stitch 5736acfc.
const shotCard = async (name) => {
  const card = document.querySelector('section[aria-label="Publicidad restada"]');
  if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/${name}.png`, element: card });
};

const wrappedMoney = () =>
  [...document.querySelectorAll('[data-money]')]
    .filter((el) => el.getClientRects().length > 1 || el.scrollWidth > el.clientWidth + 1)
    .map((el) => el.textContent.trim());

const renderPage = async (theme) => {
  await page.viewport(1366, 900);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  const screen = await render(
    <div data-shell style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}>
      <MetricasML />
    </div>,
  );
  await expect.element(screen.getByText(/Impresora Multifunción Epson EcoTank/).first()).toBeVisible();
  return screen;
};

const pick = (screen, label) => userEvent.click(screen.getByRole('button', { name: label }));

describe.each(['light', 'dark'])('Métricas ML ads toggle (%s)', (theme) => {
  it('off: no card, no adjusted marks, no ads column', async () => {
    const screen = await renderPage(theme);
    await expect.element(screen.getByText('No se resta publicidad de Total Gauss ni del markup.')).toBeVisible();
    expect(document.body.textContent).not.toContain('Publicidad restada');
    expect(document.body.textContent).not.toContain('Ajustado');
    await shot(`ads-off-${theme}`);
  });

  it('publicaciones: card, adjusted cards with the original struck through, renamed ads column', async () => {
    const screen = await renderPage(theme);
    await pick(screen, 'Restar Ads de publicaciones');
    await expect.element(screen.getByRole('region', { name: 'Publicidad restada' })).toBeVisible();
    await expect.element(screen.getByRole('columnheader', { name: /Publicidad restada \(neta de aportes\)/ })).toBeVisible();
    await expect.element(screen.getByText('Inversión (bruta)')).toBeVisible();
    expect(document.querySelectorAll('s')).toHaveLength(1);
    await expect.element(screen.getByRole('region', { name: 'Publicidad (ML Ads)' })).toBeVisible();
    expect(wrappedMoney()).toEqual([]);
    await shot(`ads-publicaciones-${theme}`);
    await shotCard(`card-publicaciones-${theme}`);
  });

  it('todo: the card breaks the subtraction into Product Ads, aportes, Display and Brand Ads', async () => {
    const screen = await renderPage(theme);
    await pick(screen, 'Restar toda la publicidad');
    const card = screen.getByRole('region', { name: 'Publicidad restada' });
    await expect.element(card.getByText('− Aportes de marcas (Display)')).toBeVisible();
    await expect.element(card.getByText('$ 18.294.119,51')).toBeVisible();
    expect(document.body.textContent).not.toContain('Con filtros solo se restan');
    await expect.element(screen.getByRole('region', { name: 'Publicidad sin producto' })).toBeVisible();
    await expect.element(screen.getByText('SIN PRODUCTO', { exact: true })).toBeVisible();
    expect(wrappedMoney()).toEqual([]);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
    await shot(`ads-todo-${theme}`);
    await shotCard(`card-todo-${theme}`);
  });

  it('todo under filters: notice and Aplicado chip, card at the publicaciones amount', async () => {
    filteredTodo = true;
    const screen = await renderPage(theme);
    await pick(screen, 'Restar toda la publicidad');
    await expect.element(screen.getByText('Con filtros solo se restan los Ads de publicaciones')).toBeVisible();
    await expect.element(screen.getByText('Aplicado: Ads de publicaciones')).toBeVisible();
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
    await shot(`ads-todo-filtrado-${theme}`);
  });
});

describe('Métricas ML "Publicidad restada" card, high contrast', () => {
  afterEach(() => document.documentElement.classList.remove('high-contrast'));

  it('keeps every chip and amount readable (4.5:1) on the card', async () => {
    document.documentElement.classList.add('high-contrast');
    const screen = await renderPage('light');
    await pick(screen, 'Restar toda la publicidad');
    const card = document.querySelector('section[aria-label="Publicidad restada"]');
    await expect.element(screen.getByRole('region', { name: 'Publicidad restada' })).toBeVisible();
    const cardBg = getComputedStyle(card).backgroundColor;
    for (const el of card.querySelectorAll('li > span:not([aria-hidden])')) {
      if (!el.textContent.trim()) continue;
      const own = getComputedStyle(el).backgroundColor;
      const bg = own === 'rgba(0, 0, 0, 0)' ? cardBg : own;
      expect(contrastRatio(getComputedStyle(el).color, bg), el.textContent).toBeGreaterThanOrEqual(4.5);
    }
    expect(wrappedMoney()).toEqual([]);
    await shotCard('card-todo-light-hc');
  });
});
