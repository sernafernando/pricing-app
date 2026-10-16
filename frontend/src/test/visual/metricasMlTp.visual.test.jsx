/**
 * Métricas ML "Costos TP" toggle — the board with the TP costs on, in real Chromium, light and dark, at the
 * 1366 width operators use: the Total TP card joins the KPI row, the Total TP column sits next to Total Gauss,
 * and an unknown Total TP reads as an "incompleto" dash. Nothing wraps or pokes out of the page. Screenshots
 * only when `VITE_METRICAS_SHOTS_DIR` is set (a DEV aid, never a committed baseline).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import MetricasML from '../../pages/MetricasML';
import api from '../../services/api';
import { BOARD_RESPONSE } from './metricasMlFixtures';
import { withTp } from '../../components/metricasMl/tpFixtures';

vi.mock('react-router-dom', () => ({
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

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url, config) => {
    if (url === '/ml-metricas/board') return Promise.resolve({ data: config?.params?.costos_tp ? withTp() : BOARD_RESPONSE });
    return Promise.resolve({ data: {} });
  });
});

const shot = async (name) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png` });
  // The table scrolls inside its card: bring Total Gauss and Total TP into view for the second shot.
  const scroller = document.querySelector('[data-table-scroll]');
  const gauss = scroller.querySelector('th[data-col-id="total_gauss"], td[data-col-id="total_gauss"]');
  scroller.scrollLeft = gauss.offsetLeft - 520;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}-tabla.png`, element: scroller });
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

describe.each(['light', 'dark'])('Métricas ML Costos TP (%s)', (theme) => {
  it('off: no Total TP card or column', async () => {
    const screen = await renderPage(theme);
    await expect.element(screen.getByRole('switch', { name: 'Costos TP' })).toBeVisible();
    expect(document.body.textContent).not.toContain('Total TP');
  });

  it('on: the Total TP card and column read whole, the KPI row stays one row', async () => {
    const screen = await renderPage(theme);
    await userEvent.click(screen.getByRole('switch', { name: 'Costos TP' }));
    await expect.element(screen.getByRole('columnheader', { name: 'Total TP' })).toBeVisible();
    await expect.element(screen.getByText('$ 3.125.400,50')).toBeVisible();
    await expect.element(screen.getByText('incompleto').first()).toBeVisible();
    expect(wrappedMoney()).toEqual([]);
    // Seven cards on one row at this width.
    const tops = [...document.querySelectorAll('section[data-tp] > div')].map((card) => card.getBoundingClientRect().top);
    expect(tops).toHaveLength(7);
    expect(new Set(tops).size).toBe(1);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
    await shot(`costos-tp-${theme}`);
  });
});
