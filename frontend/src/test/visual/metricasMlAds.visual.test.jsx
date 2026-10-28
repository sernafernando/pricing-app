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
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import MetricasML from '../../pages/MetricasML';
import api from '../../services/api';
import { BOARD_RESPONSE } from './metricasMlFixtures';
import { ADS_KPIS } from '../../components/metricasMl/adsFixtures';

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
  todo: { ...ADS_KPIS, requested: 'todo', applied: 'todo', subtracted_total: 19559119.51, unattributed: UNATTRIBUTED },
  todo_filtered: { ...ADS_KPIS, requested: 'todo', applied: 'mla', subtracted_total: 2192372.86 },
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
  it('off: no banner, no adjusted marks, no ads column', async () => {
    const screen = await renderPage(theme);
    await expect.element(screen.getByText('No se resta publicidad de Total Gauss ni del markup.')).toBeVisible();
    expect(document.body.textContent).not.toContain('Publicidad restada');
    expect(document.body.textContent).not.toContain('Ajustado');
    await shot(`ads-off-${theme}`);
  });

  it('publicaciones: banner, adjusted cards with the original struck through, ads column', async () => {
    const screen = await renderPage(theme);
    await pick(screen, 'Restar Ads de publicaciones');
    await expect.element(screen.getByText(/Publicidad restada/)).toBeVisible();
    await expect.element(screen.getByRole('columnheader', { name: /Publicidad \(inversión\)/ })).toBeVisible();
    expect(document.querySelectorAll('s')).toHaveLength(1);
    await expect.element(screen.getByRole('region', { name: 'Publicidad (ML Ads)' })).toBeVisible();
    expect(wrappedMoney()).toEqual([]);
    await shot(`ads-publicaciones-${theme}`);
  });

  it('todo: banner names the account-level spend', async () => {
    const screen = await renderPage(theme);
    await pick(screen, 'Restar toda la publicidad');
    await expect.element(screen.getByText(/sin producto y cuenta/)).toBeVisible();
    expect(document.body.textContent).not.toContain('Con filtros solo se restan');
    await expect.element(screen.getByRole('region', { name: 'Publicidad sin producto' })).toBeVisible();
    await expect.element(screen.getByText('SIN PRODUCTO', { exact: true })).toBeVisible();
    expect(wrappedMoney()).toEqual([]);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
    await shot(`ads-todo-${theme}`);
  });

  it('todo under filters: notice and Aplicado chip, banner at the publicaciones amount', async () => {
    filteredTodo = true;
    const screen = await renderPage(theme);
    await pick(screen, 'Restar toda la publicidad');
    await expect.element(screen.getByText('Con filtros solo se restan los Ads de publicaciones')).toBeVisible();
    await expect.element(screen.getByText('Aplicado: Ads de publicaciones')).toBeVisible();
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
    await shot(`ads-todo-filtrado-${theme}`);
  });
});
