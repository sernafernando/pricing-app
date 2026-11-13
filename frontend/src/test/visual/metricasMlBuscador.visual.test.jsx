/**
 * Métricas ML's search box with Publicaciones ML's operators (handoffs `metricas-buscador-tarea` T1): the real page
 * in real Chromium at 1440 (desktop) and 390 (phone), light and dark. Typing `marca:Epson` sends it to the board as
 * is (the backend parses it with Publicaciones ML's `normalize_q`), keeps it in the page's query and shows the rows
 * the board answers. The placeholder is Publicaciones ML's.
 *
 * Screenshots (a DEV aid, never a committed baseline) only when `VITE_METRICAS_SHOTS_DIR` is set.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import MetricasML from '../../pages/MetricasML';
import api from '../../services/api';
import { BOARD_RESPONSE } from './metricasMlFixtures';

vi.mock('react-router-dom', async () => ({
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
const EPSON = 'Impresora Multifunción Epson EcoTank L3250 Color Negro';
const LENOVO = 'Notebook Lenovo V15 G4 AMN Ryzen 5 8GB 256GB SSD';
const QUERY = 'marca:Epson';

// The board as the backend answers `marca:Epson`: only the Epson rows, and the total that says so.
const answer = (q) => {
  if (!q) return BOARD_RESPONSE;
  const brand = q.split(':')[1].toLowerCase();
  const rows = BOARD_RESPONSE.rows.filter((row) => row.marca?.toLowerCase() === brand);
  return { ...BOARD_RESPONSE, rows, total: rows.length };
};

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url, config) => {
    if (url === '/ml-metricas/board') return Promise.resolve({ data: answer(config?.params?.q) });
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
});

const boardQueries = () =>
  api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board').map(([, config]) => config?.params?.q);

const VIEWPORTS = {
  desktop: { width: 1440, height: 900, placeholder: 'Buscar título, MLA, SKU/EAN o producto' },
  phone: { width: 390, height: 844, placeholder: 'Título, MLA, SKU/EAN o producto' },
};

const renderPage = async (kind, theme) => {
  const { width, height } = VIEWPORTS[kind];
  await page.viewport(width, height);
  setTheme(theme);
  document.body.style.background = 'var(--cf-bg-app)';
  document.body.style.margin = '0';
  const shell =
    kind === 'desktop'
      ? { paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }
      : { paddingTop: 'var(--cf-topbar-height)', paddingLeft: 16, paddingRight: 16 };
  const screen = await render(
    <div data-shell style={shell}>
      <MetricasML />
    </div>,
  );
  await expect.element(screen.getByText(EPSON).first()).toBeVisible();
  return screen;
};

describe.each(['desktop', 'phone'])('Métricas ML search with an operator (%s)', (kind) => {
  it.each(['light', 'dark'])('sends marca:Epson as typed and shows what the board answers (%s)', async (theme) => {
    const screen = await renderPage(kind, theme);
    const box = screen.getByPlaceholder(VIEWPORTS[kind].placeholder);
    await expect.element(box).toBeVisible();
    expect(document.body.textContent).toContain(LENOVO);

    await userEvent.fill(box, QUERY);
    await expect.poll(boardQueries).toContain(QUERY);
    await expect.poll(() => document.body.textContent.includes(LENOVO)).toBe(false);
    await expect.element(screen.getByText(EPSON).first()).toBeVisible();
    await expect.element(box).toHaveValue(QUERY);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(VIEWPORTS[kind].width);

    if (!SHOTS_DIR) return;
    const name = `${SHOTS_DIR}/buscador-${kind}-${VIEWPORTS[kind].width}-${theme}`;
    await page.screenshot({ path: `${name}.png` });
    // The whole page too: the filtered rows sit below the first screen.
    const shell = document.querySelector('[data-shell]');
    await page.viewport(VIEWPORTS[kind].width, Math.max(VIEWPORTS[kind].height, shell.scrollHeight + 16));
    await page.screenshot({ path: `${name}-full.png`, element: shell });
  });
});
