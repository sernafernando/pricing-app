/**
 * Tienda Nube — the operations tab next to the real expanded sidebar, real CSS, real Chromium, invented data
 * (sell-in-costo-si T3 PR 9). A sale whose cost is unknown (the API sends a null cost: no costo SI or USD rate on its
 * date) shows "Sin costo" and a "—" ganancia and markup, never its whole clean amount as profit; a sale with a cost
 * keeps its figures. At 1440 with the sidebar open the table fits with no horizontal scroll, every amount is formatted
 * ($ 600.000) and stays on one line.
 *
 *   VITE_TN_SIN_COSTO_SHOTS_DIR=<dir> run_tests.sh frontend src/test/visual/tiendaNubeSinCosto.visual.test.jsx
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { MemoryRouter } from 'react-router-dom';
import { setTheme } from './visualHelpers';
import DashboardTiendaNube from '../../pages/DashboardTiendaNube';
import Sidebar from '../../components/Sidebar';
import layout from '../../components/AppLayout.module.css';
import api from '../../services/api';

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, tieneAlgunPermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const SHOTS_DIR = import.meta.env.VITE_TN_SIN_COSTO_SHOTS_DIR;
const ROOT_ID = 'capturas-root';

const venta = (id, descripcion, costo, over = {}) => ({
  id_operacion: id,
  metrica_id: id,
  fecha: '2026-11-18T12:00:00',
  sucursal: 'Sucursal Ejemplo',
  cliente: 'Cliente Ejemplo SA',
  marca: 'MARCA EJEMPLO',
  categoria: 'Notebooks',
  subcategoria: 'Notebooks Gamer',
  codigo_item: `NB-00${id}`,
  descripcion,
  cantidad: 1,
  precio_unitario_sin_iva: 1250000,
  iva_porcentaje: 21,
  precio_final_sin_iva: 1250000,
  monto_iva: 262500,
  precio_final_con_iva: 1512500,
  costo_unitario: costo,
  costo_pesos_sin_iva: costo,
  comision_tn_porcentaje: 1,
  comision_tn_pesos: 12500,
  monto_limpio: 1237500,
  ganancia: costo == null ? null : 1237500 - costo,
  markup: null,
  vendedor: 'Vendedor Ejemplo',
  tipo_comprobante: 'Fc',
  numero_comprobante: 'A-0001-00012345',
  ...over,
});

const OPERACIONES = [
  venta(1, 'NOTEBOOK EJEMPLO 15" 16GB 512GB CON COSTO SI', 860000),
  venta(2, 'NOTEBOOK EJEMPLO 14" SIN COTIZACION DEL DIA', null),
];

beforeEach(() => {
  vi.spyOn(api, 'get').mockImplementation((url) => {
    if (url === '/ventas-tienda-nube') return Promise.resolve({ data: OPERACIONES });
    if (url === '/pricing-constants/actual') return Promise.resolve({ data: { comision_tienda_nube: 1 } });
    if (url === '/ventas-tienda-nube/top-productos' || url === '/ventas-tienda-nube/por-marca') {
      return Promise.resolve({ data: [] });
    }
    return Promise.resolve({ data: url.startsWith('/ventas-tienda-nube') ? {} : [] });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// The app's own layout: sidebar + content offset by the expanded sidebar (AppLayout), without the top bar.
const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/dashboard-tienda-nube?tab=operaciones&fecha_desde=2026-11-01&fecha_hasta=2026-11-20']}>
      <div id={ROOT_ID} className={layout.appLayout} style={{ height: '100vh', overflow: 'hidden' }}>
        <Sidebar />
        <div className={layout.mainWrapper} data-sidebar-expanded="true" data-sidebar-hidden="false">
          <main className={layout.mainContent} style={{ marginTop: 0 }}>
            <DashboardTiendaNube />
          </main>
        </div>
      </div>
    </MemoryRouter>,
  );

const fila = (texto) => [...document.querySelectorAll('tbody tr')].find((tr) => tr.textContent.includes(texto));
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

describe('Tienda Nube operaciones (visual)', () => {
  for (const theme of ['light', 'dark']) {
    it(`1440 ${theme}: fits next to the open sidebar; sin costo shows a dash, amounts formatted on one line`, async () => {
      await page.viewport(1440, 900);
      setTheme(theme);
      renderPage();
      await expect.element(page.getByText('NOTEBOOK EJEMPLO 14" SIN COTIZACION DEL DIA')).toBeVisible();
      if (SHOTS_DIR) {
        await page.screenshot({
          path: `${SHOTS_DIR}/tn-operaciones-1440-${theme}.png`,
          element: document.getElementById(ROOT_ID),
        });
      }

      const tabla = document.querySelector('table');
      const contenedor = tabla.parentElement;
      expect(contenedor.scrollWidth).toBeLessThanOrEqual(contenedor.clientWidth + 1);
      expect(tabla.getBoundingClientRect().right).toBeLessThanOrEqual(1440);
      expect(document.body.textContent).toContain('2 operaciones');
      expect(document.body.textContent).not.toContain('operaciónes');

      const conCosto = fila('CON COSTO SI');
      const sinCosto = fila('SIN COTIZACION DEL DIA');
      expect(texto(conCosto)).toContain('$ 860.000');
      expect(texto(conCosto)).toContain('$ 1.250.000');
      expect(texto(conCosto)).toContain('$ 377.500');
      expect(texto(sinCosto)).toContain('Sin costo');
      expect(sinCosto.querySelector('td[title="Sin costo: la ganancia no se puede calcular"]')?.textContent).toBe('—');
      expect(texto(sinCosto)).not.toContain('1.237.500');

      for (const celda of document.querySelectorAll('tbody td')) {
        if (/\$\s?[\d.]+/.test(texto(celda))) expect(lineasDelImporte(celda), texto(celda)).toBe(1);
      }
    });
  }
});
