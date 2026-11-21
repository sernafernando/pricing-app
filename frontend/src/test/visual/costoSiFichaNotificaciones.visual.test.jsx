/**
 * sell-in-costo-si T3 PR 10, at 1440 next to the expanded sidebar, in both themes: the product master's read-only block
 * shows "Costo SI" next to the list cost ("Sin costo" when unknown), and a low-markup notification's unknown cost reads
 * "Sin costo" (never "$N/A"). With `VITE_COSTO_SI_PR10_SHOTS_DIR` it also takes the review screenshots:
 *
 *   VITE_COSTO_SI_PR10_SHOTS_DIR=<dir> run_tests.sh frontend src/test/visual/costoSiFichaNotificaciones.visual.test.jsx
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import api, {
  productoMaestroAPI,
  productoSpecsAPI,
  productoTnVinculosAPI,
  productoMarcasAPI,
  productoCategoriasAPI,
} from '../../services/api';
import FichaProducto from '../../components/productoMaestro/FichaProducto';
import Notificaciones from '../../pages/Notificaciones';
import Sidebar from '../../components/Sidebar';
import layout from '../../components/AppLayout.module.css';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, tieneAlgunPermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const SHOTS_DIR = import.meta.env.VITE_COSTO_SI_PR10_SHOTS_DIR;
const ROOT_ID = 'capturas-root';

const shot = async (name) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png`, element: document.getElementById(ROOT_ID) });
};

const conSidebar = (children) =>
  render(
    <MemoryRouter>
      <div id={ROOT_ID} className={layout.appLayout} style={{ height: '100vh', overflow: 'hidden' }}>
        <Sidebar />
        <div className={layout.mainWrapper} data-sidebar-expanded="true" data-sidebar-hidden="false">
          <main className={layout.mainContent} style={{ marginTop: 0 }}>
            {children}
          </main>
        </div>
      </div>
    </MemoryRouter>,
  );

const campo = (valor, gbp = valor, extra = {}) => ({ valor, gbp, overrideado: valor !== gbp, ...extra });
const texto = (valor) => ({ fuente: 'ml', elegida: false, valor, fuentes: { ml: valor, tn: null, gbp: valor } });

const maestro = (lectura) => ({
  item_id: 455,
  codigo: '4897098683446',
  tipo_specs: null,
  campos: {
    nombre: campo('Adaptador Bluetooth 5.0 TP-Link UB500 Nano USB'),
    ean: campo('4897098683446'),
    codigo_fabricante: campo('UB500'),
    marca_id: campo(12, 12, { nombre: 'TP-LINK', gbp_nombre: 'TP-LINK' }),
    categoria_id: campo(61, 61, { nombre: 'CONECTIVIDAD', gbp_nombre: 'CONECTIVIDAD' }),
    subcategoria_id: campo(3855, 3855, { nombre: 'ANTENAS WIFI', gbp_nombre: 'ANTENAS WIFI' }),
    garantia_dias: campo(180),
    peso_g: campo(35),
    ancho_cm: campo(14),
    largo_cm: campo(9),
    alto_cm: campo(3),
  },
  unidades_caja: null,
  textos: {
    titulo_ml: texto('Adaptador Bluetooth Tp-link Ub500'),
    titulo_web: texto('Adaptador Bluetooth Tp-link Ub500'),
    descripcion_ml: texto('Bluetooth 5.0'),
    descripcion_web: texto('Bluetooth 5.0'),
  },
  mla_ganadora: 'MLA1442876593',
  lectura: {
    costo: 4.6606,
    moneda_costo: 'USD',
    iva: 10.5,
    stock: 964,
    precio_lista_ml: 11999,
    proveedor: 'PC-ARTS ARGENTINA S.A.',
    publicaciones_ml: 3,
    tn_producto_id: null,
    tn_publicado: null,
    ...lectura,
  },
  can_edit: false,
  can_edit_unidades: false,
});

const mockFicha = (lectura) => {
  vi.spyOn(productoMaestroAPI, 'leer').mockResolvedValue({ data: maestro(lectura) });
  vi.spyOn(productoTnVinculosAPI, 'leer').mockResolvedValue({ data: { item_id: 455, origen: null, tn: null, can_edit: false } });
  vi.spyOn(productoTnVinculosAPI, 'candidatos').mockResolvedValue({ data: [] });
  vi.spyOn(productoMarcasAPI, 'listar').mockResolvedValue({ data: [{ id: 12, nombre: 'TP-LINK', activa: true }] });
  vi.spyOn(productoCategoriasAPI, 'listar').mockResolvedValue({
    data: [{ id: 61, nombre: 'CONECTIVIDAD', activa: true, subcategorias: [{ id: 3855, nombre: 'ANTENAS WIFI', activa: true }] }],
  });
  vi.spyOn(productoSpecsAPI, 'leer').mockResolvedValue({ data: null });
  vi.spyOn(productoSpecsAPI, 'valores').mockResolvedValue({ data: [] });
  vi.spyOn(productoSpecsAPI, 'campos').mockResolvedValue({ data: [] });
  vi.spyOn(api, 'get').mockResolvedValue({ data: [] });
};

const valorDe = (etiqueta) => page.getByText(etiqueta, { exact: true }).element().nextElementSibling;

const sinDesborde = () => {
  const main = document.querySelector('main');
  expect(main.scrollWidth).toBeLessThanOrEqual(main.clientWidth + 1);
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1440);
};

afterEach(() => vi.restoreAllMocks());

describe.each(['light', 'dark'])('Costo SI, ficha and notificaciones (%s)', (theme) => {
  beforeEach(async () => {
    await page.viewport(1440, 900);
    setTheme(theme);
  });

  it('the ficha shows Costo SI next to the list cost', async () => {
    mockFicha({ costo_si: 3.8, costo_si_moneda: 'USD', costo_si_fuente: 'costo_si' });
    conSidebar(<FichaProducto itemId={455} />);
    await expect.element(page.getByText('Costo SI', { exact: true })).toBeVisible();

    expect(valorDe('Costo').textContent).toBe('USD 4,66');
    expect(valorDe('Costo SI').textContent).toBe('USD 3,80');
    sinDesborde();
    page.getByText('Costo SI', { exact: true }).element().scrollIntoView({ block: 'center' });
    await shot(`ficha-costo-si-1440-${theme}`);
  });

  it('the ficha says "Sin costo" when no cost is known', async () => {
    mockFicha({ costo_si: null, costo_si_moneda: null, costo_si_fuente: null });
    conSidebar(<FichaProducto itemId={455} />);
    await expect.element(page.getByText('Costo SI', { exact: true })).toBeVisible();

    expect(valorDe('Costo SI').textContent).toBe('Sin costo');
    page.getByText('Costo SI', { exact: true }).element().scrollIntoView({ block: 'center' });
    await shot(`ficha-sin-costo-1440-${theme}`);
  });

  it('a notification with an unknown current cost reads "Sin costo"', async () => {
    const reciente = {
      id: 5,
      tipo: 'markup_bajo',
      mensaje: 'Markup bajo',
      leida: true,
      severidad: 'WARNING',
      estado: 'PENDIENTE',
      fecha_creacion: '2026-11-14T10:00:00Z',
      item_id: 9000,
      markup_real: -4.5,
      monto_venta: 20000,
      fecha_venta: '2026-11-13T09:00:00Z',
      costo_operacion: 1234.5,
      costo_actual: null,
    };
    const grupo = {
      item_id: 9000,
      tipo: 'markup_bajo',
      markup_real: -4.5,
      codigo_producto: 'COD-9000',
      descripcion_producto: 'Producto 9000',
      pm: null,
      count: 1,
      primera_fecha: '2026-11-13T09:00:00Z',
      ultima_fecha: '2026-11-13T09:00:00Z',
      notificacion_reciente: reciente,
      notificaciones_ids: [5],
    };
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/notificaciones/stats') return Promise.resolve({ data: { total: 1, no_leidas: 0, por_tipo: {} } });
      if (url === '/notificaciones/agrupadas') return Promise.resolve({ data: [grupo] });
      return Promise.resolve({ data: {} });
    });
    conSidebar(<Notificaciones />);
    await page.getByText('COD-9000 - Producto 9000').click();
    await expect.element(page.getByText('Costo Actual:')).toBeVisible();

    expect(valorDe('Costo Actual:').textContent).toBe('Sin costo');
    expect(valorDe('Costo de la Venta:').textContent).toBe('$1.234,50');
    sinDesborde();
    page.getByText('Costo Actual:').element().scrollIntoView({ block: 'center' });
    await shot(`notificaciones-sin-costo-1440-${theme}`);
  });
});
