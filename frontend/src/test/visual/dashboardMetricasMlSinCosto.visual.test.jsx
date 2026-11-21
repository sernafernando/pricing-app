/**
 * Dashboard Métricas ML, Detalle de Operaciones — a sale without a known cost (costo SI interface §7: the backend
 * returns a null cost, costo total and markup) reads "sin costo" ("—", secondary text) in its three cells instead of
 * $0 / 0.00 %, at 1440 next to the expanded sidebar, in both themes. With `VITE_DASHBOARD_ML_SHOTS_DIR` it also takes
 * the review screenshots. The operations table fits 1440 next to the expanded sidebar (every column, the markup
 * included, inside its container, amounts on one line, stacked headers keep their "/" with the first word):
 *
 *   VITE_DASHBOARD_ML_SHOTS_DIR=<dir> run_tests.sh frontend src/test/visual/dashboardMetricasMlSinCosto.visual.test.jsx
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme, tokenColor } from './visualHelpers';
import api from '../../services/api';
import DashboardMetricasML from '../../pages/DashboardMetricasML';
import Sidebar from '../../components/Sidebar';
import layout from '../../components/AppLayout.module.css';
import { seedTiendasOficiales, resetTiendasOficiales } from '../tiendasOficialesFixtures';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, tieneAlgunPermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const SHOTS_DIR = import.meta.env.VITE_DASHBOARD_ML_SHOTS_DIR;
const ROOT_ID = 'capturas-root';

const operacion = (id, codigo, costo) => ({
  id_operacion: id,
  ml_id: `200000${id}`,
  fecha_venta: '2026-10-05T15:00:00',
  item_id: 6000 + id,
  codigo,
  descripcion: `Cámara IP Demo Domo 4MP Exterior Visión Nocturna ${codigo}`,
  marca: 'MARCA DEMO',
  categoria: 'CAMARAS',
  cantidad: '1',
  monto_unitario: '1250000',
  monto_total: '1250000',
  iva: '21',
  pricelist_id: 4,
  tipo_publicacion: 'Clásica',
  costo_sin_iva: costo,
  costo_total: costo,
  comision_porcentaje: '12',
  comision_pesos: '150000',
  costo_envio: '12500',
  monto_limpio: '1087500',
  markup_porcentaje: costo === null ? null : '26.45',
  offset_flex: '0',
  is_cancelled: false,
});

const OPERACIONES = [operacion(1, 'SINCOSTO', null), operacion(2, 'CONCOSTO', '860000')];

beforeEach(() => {
  seedTiendasOficiales([{ store_id: 57997, nombre: 'Tienda Demo', clave: null, orden: 0, activa: true }]);
  vi.spyOn(api, 'get').mockImplementation((url) =>
    Promise.resolve({
      data: url.includes('operaciones-con-metricas')
        ? OPERACIONES
        : url.includes('disponibles') || url.includes('/usuarios/pms') || url.includes('por-')
          ? []
          : {},
    }),
  );
});

afterAll(() => {
  resetTiendasOficiales();
  vi.restoreAllMocks();
});

const shot = async (name) => {
  if (!SHOTS_DIR) return;
  await page.screenshot({ path: `${SHOTS_DIR}/${name}.png`, element: document.getElementById(ROOT_ID) });
};

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/dashboard-metricas-ml?tab=operaciones']}>
      <div id={ROOT_ID} className={layout.appLayout} style={{ height: '100vh', overflow: 'hidden' }}>
        <Sidebar />
        <div className={layout.mainWrapper} data-sidebar-expanded="true" data-sidebar-hidden="false">
          <main className={layout.mainContent} style={{ marginTop: 0 }}>
            <DashboardMetricasML />
          </main>
        </div>
      </div>
    </MemoryRouter>,
  );

// Intl writes "$\u00a0860.000": compare with a plain space.
const texto = (el) => el.textContent.replace(/\u00a0/g, ' ');
// The lines an amount's own text takes (its text node only, not the cell's other content).
const lineasDelImporte = (celda) => {
  const walker = document.createTreeWalker(celda, NodeFilter.SHOW_TEXT);
  for (let nodo = walker.nextNode(); nodo; nodo = walker.nextNode()) {
    if (!/\$\s?[\d.]/.test(nodo.textContent.replace(/\u00a0/g, ' '))) continue;
    const rango = document.createRange();
    rango.selectNodeContents(nodo);
    return new Set([...rango.getClientRects()].map((r) => Math.round(r.top))).size;
  }
  return 0;
};
// The nearest ancestor that clips or scrolls the table sideways.
const contenedorDe = (tabla) => {
  for (let nodo = tabla.parentElement; nodo; nodo = nodo.parentElement) {
    if (['auto', 'scroll', 'hidden'].includes(getComputedStyle(nodo).overflowX)) return nodo;
  }
  return document.documentElement;
};

describe.each(['light', 'dark'])('Dashboard Métricas ML, sale without cost (%s)', (theme) => {
  beforeEach(async () => {
    await page.viewport(1440, 900);
    setTheme(theme);
  });

  it('the unknown cost, costo total and markup read "sin costo" in secondary text, the known sale keeps its figures', async () => {
    renderPage();
    const fila = page.getByRole('row').filter({ hasText: 'SINCOSTO' });
    await expect.element(fila).toBeVisible();

    const marcas = fila.getByLabelText('Sin costo').elements();
    expect(marcas).toHaveLength(3);
    for (const marca of marcas) {
      expect(marca.textContent).toBe('—');
      expect(getComputedStyle(marca).color).toBe(tokenColor('--text-secondary'));
    }
    const conCosto = page.getByRole('row').filter({ hasText: 'CONCOSTO' });
    await expect.element(conCosto.getByText('26.45%')).toBeVisible();
    expect(conCosto.getByLabelText('Sin costo').elements()).toHaveLength(0);

    await shot(`dashboard-ml-operaciones-sin-costo-1440-${theme}`);
  });

  it('the operations table fits 1440 next to the open sidebar: markup on screen, amounts on one line', async () => {
    renderPage();
    await expect.element(page.getByRole('row').filter({ hasText: 'SINCOSTO' })).toBeVisible();

    const tabla = document.querySelector('table');
    const contenedor = contenedorDe(tabla);
    expect(contenedor.scrollWidth).toBeLessThanOrEqual(contenedor.clientWidth + 1);
    const borde = Math.min(contenedor.getBoundingClientRect().right, 1440);
    expect(tabla.getBoundingClientRect().right).toBeLessThanOrEqual(borde + 1);
    for (const marca of page.getByLabelText('Sin costo').elements()) {
      expect(marca.getBoundingClientRect().right).toBeLessThanOrEqual(borde);
    }
    const conCosto = page.getByRole('row').filter({ hasText: 'CONCOSTO' });
    expect(conCosto.getByText('26.45%').element().getBoundingClientRect().right).toBeLessThanOrEqual(borde);
    expect(document.body.textContent).toContain('2 operaciones');
    expect(document.body.textContent).not.toContain('operaciónes');
    // a stacked header keeps its "/" with the first word: the first line ends in "/", never a lone "/"
    for (const th of [...tabla.querySelectorAll('th')].filter((h) => h.textContent.includes('/'))) {
      const rango = document.createRange();
      rango.selectNodeContents(th);
      const tops = [...rango.getClientRects()].map((r) => Math.round(r.top));
      const barra = document.createRange();
      const nodo = th.firstChild;
      barra.setStart(nodo, nodo.textContent.indexOf('/'));
      barra.setEnd(nodo, nodo.textContent.indexOf('/') + 1);
      expect(Math.round(barra.getClientRects()[0].top), th.textContent).toBe(Math.min(...tops));
    }
    for (const celda of document.querySelectorAll('tbody td')) {
      if (/\$\s?[\d.]+/.test(texto(celda))) expect(lineasDelImporte(celda), texto(celda)).toBe(1);
    }
  });
});
