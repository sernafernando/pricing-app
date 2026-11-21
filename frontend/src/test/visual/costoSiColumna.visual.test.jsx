/**
 * Costo SI second column (costo SI T3 PR 3, S1): Productos and Tienda show the costo SI right after the list cost, at
 * 1440 next to the expanded sidebar, in both themes. An unknown costo SI reads "—", never 0 (interface §7). With
 * `VITE_COSTO_SI_SHOTS_DIR` it also takes the review screenshots:
 *
 *   VITE_COSTO_SI_SHOTS_DIR=<dir> run_tests.sh frontend src/test/visual/costoSiColumna.visual.test.jsx
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import api from '../../services/api';
import Productos from '../../pages/Productos';
import Tienda from '../../pages/Tienda';
import Sidebar from '../../components/Sidebar';
import layout from '../../components/AppLayout.module.css';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, tieneAlgunPermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));
vi.mock('../../hooks/useSSEChannel', () => ({ useSSEChannel: vi.fn() }));

const SHOTS_DIR = import.meta.env.VITE_COSTO_SI_SHOTS_DIR;
const ROOT_ID = 'capturas-root';

const costoSi = (costo, moneda, fuente, costoArs) => ({
  costo,
  moneda,
  fuente,
  desde: fuente === 'costo_si' ? '2026-10-01' : null,
  tipo_cambio: moneda === 'USD' && costoArs != null ? 1000 : null,
  tipo_cambio_fecha: moneda === 'USD' && costoArs != null ? '2026-11-20' : null,
  costo_ars: costoArs,
});

const producto = (id, codigo, overrides) => ({
  item_id: id,
  codigo,
  descripcion: `Cámara IP Demo Domo 4MP Exterior ${codigo}`,
  marca: 'MARCA DEMO',
  categoria: 'CAMARAS',
  subcategoria: 'Domos',
  stock: 12,
  moneda_costo: 'USD',
  costo: 30,
  costo_ars: 30000,
  tipo_cambio: 1000,
  precio_lista_ml: 52000,
  markup: 22.5,
  precio_gremio_sin_iva: 38000,
  precio_gremio_con_iva: 45980,
  markup_gremio: 20,
  precio_sugerido_sin_iva: 41000,
  precio_sugerido_con_iva: 49610,
  markup_sugerido_total: 30,
  sell_in_out: null,
  ...overrides,
});

const PRODUCTOS = [
  producto(9101, 'CONSI-USD', { costo_si: costoSi(25, 'USD', 'costo_si', 25000) }),
  producto(9102, 'CONSI-ARS', { moneda_costo: 'ARS', costo: 64000, costo_si: costoSi(61000, 'ARS', 'costo_si', 61000) }),
  producto(9103, 'LISTA', { costo_si: costoSi(30, 'USD', 'lista', 30000) }),
  producto(9104, 'SIN-TC', { costo_si: costoSi(25, 'USD', 'costo_si', null) }),
  producto(9105, 'SIN-COSTO', { costo_si: null }),
];

beforeEach(() => {
  vi.spyOn(api, 'get').mockImplementation((url) => {
    if (url === '/productos' || url === '/productos/tienda') {
      return Promise.resolve({ data: { productos: PRODUCTOS, total: PRODUCTOS.length } });
    }
    if (url === '/tipo-cambio-hoy') return Promise.resolve({ data: { tipo_cambio: 1000 } });
    if (url === '/tipo-cambio/actual') return Promise.resolve({ data: { compra: 1000, venta: 1000 } });
    if (url.startsWith('/auditoria') || url.startsWith('/usuarios/pms') || url === '/offsets-ganancia' || url.startsWith('/equipos')) {
      return Promise.resolve({ data: [] });
    }
    if (url === '/marcas') return Promise.resolve({ data: { marcas: [] } });
    if (url === '/subcategorias') return Promise.resolve({ data: { categorias: [] } });
    return Promise.resolve({ data: {} });
  });
});

afterAll(() => vi.restoreAllMocks());

const shot = async (name) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png`, element: document.getElementById(ROOT_ID) });
};

const renderPage = (Page, path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <div id={ROOT_ID} className={layout.appLayout} style={{ height: '100vh', overflow: 'hidden' }}>
        <Sidebar />
        <div className={layout.mainWrapper} data-sidebar-expanded="true" data-sidebar-hidden="false">
          <main className={layout.mainContent} style={{ marginTop: 0 }}>
            <Page />
          </main>
        </div>
      </div>
    </MemoryRouter>,
  );

// The cell under the "Costo SI" header in a product's row.
const costoSiCell = (codigo) => {
  const headers = [...document.querySelectorAll('thead th')];
  const col = headers.findIndex((th) => th.textContent.trim().startsWith('Costo SI'));
  const row = [...document.querySelectorAll('tbody tr')].find((tr) => tr.textContent.includes(codigo));
  return row?.children[col];
};

describe.each([
  ['productos', Productos, '/productos'],
  ['tienda', Tienda, '/tienda'],
])('Costo SI column on %s', (name, Page, path) => {
  describe.each(['light', 'dark'])('%s theme', (theme) => {
    beforeEach(async () => {
      await page.viewport(1440, 1400); // tall enough for the five rows, the "—" ones included
      setTheme(theme);
    });

    it('sits right after the list cost; an unknown costo SI reads "—", never 0', async () => {
      renderPage(Page, path);
      await expect.element(page.getByText('CONSI-USD', { exact: false }).first()).toBeVisible();

      const headers = [...document.querySelectorAll('thead th')].map((th) => th.textContent.trim());
      const col = headers.findIndex((h) => h.startsWith('Costo SI'));
      expect(col).toBeGreaterThan(0);
      expect(headers[col - 1]).toMatch(/^Costo/);
      expect(costoSiCell('SIN-COSTO').textContent.trim()).toBe('—');
      expect(costoSiCell('LISTA').textContent).toContain('lista');
      for (const codigo of ['CONSI-USD', 'CONSI-ARS', 'LISTA', 'SIN-TC', 'SIN-COSTO']) {
        expect(costoSiCell(codigo).textContent).not.toMatch(/(^|\D)0([.,]00)?$/);
      }

      await shot(`${name}-costo-si-1440-${theme}`);
    });
  });
});
