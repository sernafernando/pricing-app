/**
 * Tienda Gremio / Sugerido over costo SI (costo SI T3 PR 6, owner L20: "los precios de gremio y sugerido toman costo
 * si"), at 1440 next to the expanded sidebar, in both themes:
 * - a product whose costo SI has no pesos shows no Gremio / Sugerido price, and says why, never a price over 0 (§7);
 * - Ctrl + click on Gremio builds the price from a markup over the costo SI (the preview), and refuses without it.
 * With `VITE_TIENDA_GREMIO_SHOTS_DIR` it also takes the review screenshots:
 *
 *   VITE_TIENDA_GREMIO_SHOTS_DIR=<dir> run_tests.sh frontend src/test/visual/tiendaGremioCostoSi.visual.test.jsx
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render } from 'vitest-browser-react';
import { page, userEvent } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import api from '../../services/api';
import Tienda from '../../pages/Tienda';
import Sidebar from '../../components/Sidebar';
import layout from '../../components/AppLayout.module.css';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, tieneAlgunPermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));
vi.mock('../../hooks/useSSEChannel', () => ({ useSSEChannel: vi.fn() }));

const SHOTS_DIR = import.meta.env.VITE_TIENDA_GREMIO_SHOTS_DIR;
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

// As `/productos/tienda` returns them: Gremio = costo SI x 1.065 x (1 + 20%), Sugerido x (1 + 30%).
const producto = (id, codigo, costoSiArs, overrides) => ({
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
  precio_gremio_sin_iva: costoSiArs * 1.065 * 1.2,
  precio_gremio_con_iva: costoSiArs * 1.065 * 1.2 * 1.21,
  markup_gremio: 20,
  precio_sugerido_sin_iva: costoSiArs * 1.065 * 1.3,
  precio_sugerido_con_iva: costoSiArs * 1.065 * 1.3 * 1.21,
  markup_sugerido_total: 30,
  tiene_override_gremio: false,
  sell_in_out: null,
  iva: 21,
  ...overrides,
});

const PRODUCTOS = [
  producto(9201, 'CONSI-USD', 25000, { costo_si: costoSi(25, 'USD', 'costo_si', 25000) }),
  producto(9202, 'LISTA', 30000, { costo_si: costoSi(30, 'USD', 'lista', 30000) }),
  producto(9203, 'SIN-TC', 0, {
    costo: 28,
    markup: null,
    precio_gremio_sin_iva: null,
    precio_gremio_con_iva: null,
    precio_sugerido_sin_iva: null,
    precio_sugerido_con_iva: null,
    markup_sugerido_total: null,
    costo_si: costoSi(25, 'USD', 'costo_si', null),
  }),
];

beforeEach(() => {
  vi.spyOn(api, 'get').mockImplementation((url) => {
    if (url === '/productos/tienda') return Promise.resolve({ data: { productos: PRODUCTOS, total: PRODUCTOS.length } });
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

const renderTienda = () =>
  render(
    <MemoryRouter initialEntries={['/tienda']}>
      <div id={ROOT_ID} className={layout.appLayout} style={{ height: '100vh', overflow: 'hidden' }}>
        <Sidebar />
        <div className={layout.mainWrapper} data-sidebar-expanded="true" data-sidebar-hidden="false">
          <main className={layout.mainContent} style={{ marginTop: 0 }}>
            <Tienda />
          </main>
        </div>
      </div>
    </MemoryRouter>,
  );

const fila = (codigo) => [...document.querySelectorAll('tbody tr')].find((tr) => tr.textContent.includes(codigo));
const gremio = (codigo) => fila(codigo).querySelector('.gremio-container');

describe.each(['light', 'dark'])('Tienda Gremio / Sugerido over costo SI, %s theme', (theme) => {
  beforeEach(async () => {
    await page.viewport(1440, 1000);
    setTheme(theme);
  });

  it('prices over costo SI; without pesos there is no price and the cell says why', async () => {
    renderTienda();
    await expect.element(page.getByText('CONSI-USD', { exact: false }).first()).toBeVisible();

    expect(fila('CONSI-USD').textContent).toContain('31.950,00'); // 25000 x 1.065 x 1.2
    expect(fila('LISTA').textContent).toContain('38.340,00'); // the list cost without a costo SI step (Q1)
    const sinTc = fila('SIN-TC').textContent;
    expect(sinTc).toContain('Sin costo en pesos: no se calcula');
    expect(sinTc).not.toMatch(/\$\s?0,00/);

    await shot(`tienda-gremio-costo-si-1440-${theme}`);
  });

  it('Ctrl + click on Gremio previews the price over costo SI, and refuses without it', async () => {
    renderTienda();
    await expect.element(page.getByText('CONSI-USD', { exact: false }).first()).toBeVisible();

    await userEvent.click(gremio('CONSI-USD'), { modifiers: ['Control'] });
    await userEvent.fill(page.getByPlaceholder('Ej: 15 o -5'), '20');
    // the client's preview: costo SI 25000 x 1.07 x 1.2 (its varios 7, see the PR body)
    await expect.element(page.getByText('Preview: $32.100,00 s/IVA')).toBeVisible();
    await shot(`tienda-gremio-markup-preview-1440-${theme}`);

    await userEvent.keyboard('{Escape}');
    await userEvent.click(gremio('SIN-TC'), { modifiers: ['Control'] });
    await userEvent.fill(page.getByPlaceholder('Ej: 15 o -5'), '20');
    await expect.element(page.getByText('Sin costo SI en pesos: no se calcula')).toBeVisible();
    // a warning, not the green "price ready" badge
    await expect.element(page.getByText('Sin costo SI en pesos: no se calcula')).toHaveClass('warning-badge');
    await shot(`tienda-gremio-markup-sin-costo-1440-${theme}`);
  });
});
