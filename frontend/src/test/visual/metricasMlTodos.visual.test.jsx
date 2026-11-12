/**
 * Métricas ML "Todos" (filas-sin-limite S3) in real Chromium: the board scrolls INSIDE its card scroller
 * (same sticky model as Publicaciones ML), so virtualization (`kit/useVirtualRows` on that scroller) must keep
 * the rows in view in the DOM with no blank gap, and the next part must come in when the table's end is reached.
 * jsdom lays nothing out, so this cannot be a unit test.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import MetricasML from '../../pages/MetricasML';
import api from '../../services/api';
import { BOARD_RESPONSE, BOARD_ROWS } from './metricasMlFixtures';

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
  default: {
    get: vi.fn(),
    post: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
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


// "Todos" over 2500 rows: a first part of 2000, then the last 500 when the table's end comes into view.
const TOTAL = 2500;
const row = (i) => ({ ...BOARD_ROWS[0], key: String(i), product_item_id: i, title: `Producto de prueba ${i}`, sku: `SKU-${i}` });
const routeGet = (url, { params } = {}) => {
  if (url === '/ml-metricas/board') {
    if (params?.limit !== 2000) return { data: BOARD_RESPONSE };
    const rows = Array.from({ length: Math.min(2000, TOTAL - params.offset) }, (_, i) => row(params.offset + i));
    return { data: { ...BOARD_RESPONSE, total: TOTAL, limit: 2000, offset: params.offset, rows } };
  }
  if (url === '/usuarios/pms') return { data: [] };
  return { data: {} };
};

const SHOTS_DIR = import.meta.env.VITE_METRICAS_SHOTS_DIR;

const Shell = ({ children }) => (
  <div
    data-shell
    style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-collapsed)' }}
  >
    {children}
  </div>
);

const frames = (n = 3) =>
  new Promise((resolve) => {
    const step = (left) => (left === 0 ? resolve() : requestAnimationFrame(() => step(left - 1)));
    step(n);
  });

const boardRows = () => [...document.querySelectorAll('tbody[data-index]')];
const scrollerOf = () => document.querySelector('[data-table-scroll]');

// The rows in the DOM cover the scroller with no gap: the first one starts at or above the scroller's top and the
// last one ends at or below its bottom (when there are rows left), so scrolling lands on real rows, never blanks.
const coversScroller = () => {
  const scroller = scrollerOf();
  const box = scroller.getBoundingClientRect();
  const blocks = boardRows();
  const top = blocks[0].getBoundingClientRect().top;
  const bottom = blocks.at(-1).getBoundingClientRect().bottom;
  return top <= box.top + 1 && bottom >= box.bottom - 1;
};

describe('Métricas ML "Todos" in real Chromium (filas-sin-limite S3)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url, config) => Promise.resolve(routeGet(url, config)));
  });

  it('renders only the rows in view while the card scroller moves, and loads the next part at the end', async () => {
    await page.viewport(1440, 900);
    setTheme('light');
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(
      <Shell>
        <MetricasML />
      </Shell>,
    );
    await expect.element(screen.getByText(/Impresora Multifunción Epson EcoTank/).first()).toBeVisible();
    await screen.getByLabelText('Filas por página').selectOptions('Todos');
    await expect.element(screen.getByText('Producto de prueba 0').first()).toBeVisible();
    expect(boardRows().length).toBeLessThan(80);

    const scroller = scrollerOf();
    expect(getComputedStyle(scroller).overflowY).toBe('auto');
    expect(scroller.scrollHeight).toBeGreaterThan(scroller.clientHeight);

    // Halfway through the first part: the rows there are in the DOM and cover the scroller.
    scroller.scrollTop = 1000 * 40;
    await frames();
    await frames();
    expect(boardRows().length).toBeLessThan(80);
    expect(coversScroller()).toBe(true);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/metricas-todos-mitad.png` });

    // To the end: the last part comes in, and its last row is reachable.
    for (let i = 0; i < 6; i += 1) {
      scroller.scrollTop = scroller.scrollHeight;
      await frames();
    }
    await expect.poll(() => api.get.mock.calls.some(([, config]) => config?.params?.offset === 2000)).toBe(true);
    for (let i = 0; i < 6; i += 1) {
      scroller.scrollTop = scroller.scrollHeight;
      await frames();
    }
    await expect.element(screen.getByText('Producto de prueba 2499').first()).toBeInTheDocument();
    expect(boardRows().length).toBeLessThan(80);
    expect(document.querySelector('[data-shell]').textContent.replace(/\s+/g, ' ')).toMatch(/Mostrando 1–2500 de 2\.500 productos/);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/metricas-todos-final.png` });
  });
});
