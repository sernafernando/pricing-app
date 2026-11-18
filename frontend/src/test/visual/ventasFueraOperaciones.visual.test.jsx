/**
 * Operaciones por Fuera (ODD `vpf-operaciones` S2) beside the Ventas ML operations screen it is modelled on, in
 * real Chromium with the app's CSS, at a laptop width and a phone width. One document is opened, showing its lines:
 * a Sin producto line with its cause, a Manual fix and a line to review. Invented data only (public repo).
 *
 * Screenshots (a DEV aid, never a committed baseline) only when `VITE_VENTAS_FUERA_SHOTS_DIR` is set:
 *
 *   VITE_VENTAS_FUERA_SHOTS_DIR=/abs/dir run_tests.sh frontend src/test/visual/ventasFueraOperaciones.visual.test.jsx --project=visual
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import VentasFueraOperaciones from '../../pages/VentasFueraOperaciones';
import VentasML from '../../pages/VentasML';
import api from '../../services/api';
import { LISTADO, RESUMEN_SIN_PRODUCTO } from '../../components/ventasFueraOperaciones/fixtures';
import { SALES_RESPONSE, KPI_RESPONSE, ORDER_DETAIL_RESPONSE, PACK_DETAIL_RESPONSE } from './ventasMlFixtures';

// Same isolation the other page-level visual tests use: a live react-router-dom pulls a second React graph into
// browser mode. Ventas ML only needs search params and a Link; Operaciones por Fuera uses neither.
vi.mock('react-router-dom', async () => {
  const { useState } = await import('react');
  return {
    useSearchParams: () => {
      const [params, setParams] = useState(() => new URLSearchParams());
      return [params, (next) => setParams(new URLSearchParams(typeof next === 'function' ? next(params) : next))];
    },
    Link: ({ to, children, ...rest }) => (
      <a href={to} {...rest}>
        {children}
      </a>
    ),
  };
});

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
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
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, tieneAlgunPermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const routeGet = (url) => {
  if (url === '/ventas-fuera-pdf/operaciones/listado') return { data: LISTADO };
  if (url === '/ventas-fuera-pdf/sin-producto/resumen') return { data: RESUMEN_SIN_PRODUCTO };
  if (url === '/ml-ventas-ops/sales') return { data: SALES_RESPONSE };
  if (url === '/ml-ventas-ops/sales/kpis') return { data: KPI_RESPONSE };
  if (url === '/ml-ventas-ops/sales/sync-status') return { data: { last_synced_at: new Date().toISOString() } };
  if (url.startsWith('/ml-ventas-ops/orders/')) return { data: ORDER_DETAIL_RESPONSE };
  if (url.startsWith('/ml-ventas-ops/packs/')) return { data: PACK_DETAIL_RESPONSE };
  if (url === '/usuarios/pms') return { data: [] };
  return { data: {} };
};

const SHOTS_DIR = import.meta.env.VITE_VENTAS_FUERA_SHOTS_DIR;
// The viewport as the operator sees it, plus the whole page laid out at that width (`-full`), so the lines below
// the fold are seen too.
const shot = async (name, { width, height, name: sizeName }) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png` });
  // On a phone the lines panel covers the screen (SplitPanelLayout): the viewport shot is the whole story.
  if (sizeName === 'phone') return;
  const shell = document.querySelector('[data-shell]');
  await page.viewport(width, Math.max(height, shell.scrollHeight + 16));
  await page.screenshot({ path: `${SHOTS_DIR}/${name}-full.png`, element: shell });
  await page.viewport(width, height);
};

const SIZES = [
  { name: 'desktop', width: 1366, height: 768 },
  { name: 'phone', width: 390, height: 844 },
];

// The app shell on a laptop: fixed TopBar and the collapsed sidebar. A phone has the TopBar only.
const Shell = ({ phone, children }) => (
  <div
    data-shell
    style={{
      paddingTop: 'var(--cf-topbar-height)',
      paddingLeft: phone ? 0 : 'var(--cf-sidebar-width-collapsed)',
    }}
  >
    {children}
  </div>
);

const mount = async ({ width, height, name }, contenido) => {
  await page.viewport(width, height);
  setTheme('light');
  document.body.style.background = 'var(--cf-bg-app)';
  return render(
    <Shell phone={name === 'phone'}>
      {contenido}
    </Shell>,
  );
};

describe('Operaciones por Fuera (visual)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url) => Promise.resolve(routeGet(url)));
  });

  for (const size of SIZES) {
    it(`${size.name} ${size.width}: a document open shows its lines, flags and causes; nothing scrolls sideways`, async () => {
      const screen = await mount(size, <VentasFueraOperaciones />);
      await expect.element(screen.getByText('Fc A 00008-00018044')).toBeVisible();
      await shot(`operaciones-por-fuera-${size.name}-lista`, size);
      await screen.getByText('Fc A 00008-00018044').click();

      const panel = screen.getByRole('complementary', { name: 'Líneas del comprobante' });
      await expect.element(panel.getByText('Artículo manual, sin código')).toBeVisible();
      await expect.element(panel.getByText('Manual', { exact: true })).toBeVisible();
      await expect.element(panel.getByText('Revisar', { exact: true })).toBeVisible();
      await expect.element(panel.getByRole('button', { name: 'Editar costo de la línea 2' })).toBeVisible();

      const aside = document.querySelector('aside[aria-label="Líneas del comprobante"]');
      expect(aside.getBoundingClientRect().right).toBeLessThanOrEqual(size.width + 1);
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(size.width);
      await shot(`operaciones-por-fuera-${size.name}`, size);

      if (size.name === 'desktop') {
        // The list beside the panel, as on Ventas ML: the panel shrinks the table, never covers it.
        const tabla = document.querySelector('table[aria-label="Operaciones"]');
        expect(tabla.closest('[data-table-shell-scroller]').getBoundingClientRect().right).toBeLessThanOrEqual(
          aside.getBoundingClientRect().left + 1,
        );
      }
      screen.unmount();
    });
  }
});

describe('Ventas ML operations screen, the model (visual reference)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url) => Promise.resolve(routeGet(url)));
  });

  for (const size of SIZES) {
    it(`${size.name} ${size.width}: renders the list for the screenshot pair`, async () => {
      const screen = await mount(size, <VentasML />);
      await expect.element(screen.getByText(/Impresora Multifunción Epson/).first()).toBeVisible();
      await shot(`ventas-ml-${size.name}`, size);
      screen.unmount();
    });
  }
});
