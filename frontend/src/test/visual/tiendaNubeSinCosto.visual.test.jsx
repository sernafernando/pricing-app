/**
 * Tienda Nube — the operations tab in real Chromium with the app's CSS (sell-in-costo-si T3 PR 9). A sale whose cost is
 * unknown (the API sends a null cost: no costo SI or USD rate on its date) shows "Sin costo" and a "—" ganancia and
 * markup, never its whole clean amount as profit; a sale with a cost keeps its figures.
 *
 * Screenshots (a DEV aid, never a committed baseline) only when `VITE_TN_SIN_COSTO_SHOTS_DIR` is set.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import DashboardTiendaNube from '../../pages/DashboardTiendaNube';
import api from '../../services/api';

vi.mock('react-router-dom', async () => ({
  ...(await import('./searchParamsMock')),
  useNavigate: () => () => {},
  Link: ({ to, children, ...rest }) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock('../../hooks/useQueryFilters', () => ({
  useQueryFilters: (defaults) => ({
    getFilter: (k) => ({ ...defaults, tab: 'operaciones', fecha_desde: '2026-11-01', fecha_hasta: '2026-11-20' })[k],
    updateFilters: () => {},
  }),
}));

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, tieneAlgunPermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const SHOTS_DIR = import.meta.env.VITE_TN_SIN_COSTO_SHOTS_DIR;

const venta = (id, descripcion, costo) => ({
  id_operacion: id,
  metrica_id: id,
  fecha: '2026-11-18T12:00:00',
  sucursal: 'Sucursal Ejemplo',
  cliente: 'Cliente Ejemplo',
  marca: 'MARCA EJEMPLO',
  categoria: 'Notebooks',
  subcategoria: 'Notebooks',
  codigo_item: `C${id}`,
  descripcion,
  cantidad: 1,
  precio_unitario_sin_iva: 1000000,
  iva_porcentaje: 21,
  precio_final_sin_iva: 1000000,
  monto_iva: 210000,
  precio_final_con_iva: 1210000,
  costo_unitario: costo,
  costo_pesos_sin_iva: costo,
  comision_tn_porcentaje: 1,
  comision_tn_pesos: 10000,
  monto_limpio: 990000,
  ganancia: costo == null ? null : 990000 - costo,
  markup: null,
  vendedor: 'Vendedor Ejemplo',
  tipo_comprobante: 'Fc',
  numero_comprobante: 'A-0001',
});

const OPERACIONES = [venta(1, 'NOTEBOOK CON COSTO SI', 600000), venta(2, 'NOTEBOOK SIN COTIZACION DEL DIA', null)];

// Fixed 56px TopBar + EXPANDED sidebar, as asked for the PR captures.
const Shell = ({ children }) => (
  <div style={{ paddingTop: 'var(--cf-topbar-height)', paddingLeft: 'var(--cf-sidebar-width-expanded)' }}>{children}</div>
);

describe('Tienda Nube operaciones sin costo (visual)', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url === '/ventas-tienda-nube') return Promise.resolve({ data: OPERACIONES });
      if (url === '/pricing-constants/actual') return Promise.resolve({ data: { comision_tienda_nube: 1 } });
      if (url === '/ventas-tienda-nube/top-productos' || url === '/ventas-tienda-nube/por-marca') {
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: {} });
    });
  });

  for (const theme of ['light', 'dark']) {
    it(`1440 ${theme}: an unknown cost shows sin costo and no ganancia, a known one keeps its figures`, async () => {
      await page.viewport(1440, 900);
      setTheme(theme);
      document.body.style.background = 'var(--cf-bg-app)';
      const screen = await render(
        <Shell>
          <DashboardTiendaNube />
        </Shell>,
      );
      await expect.element(screen.getByText('NOTEBOOK SIN COTIZACION DEL DIA')).toBeVisible();
      // the cost / ganancia / markup columns sit at the right end of the table's own horizontal scroll
      for (let el = document.querySelector('table'); el; el = el.parentElement) el.scrollLeft = el.scrollWidth;
      window.scrollTo(document.documentElement.scrollWidth, 0);
      if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/tn-sin-costo-1440-${theme}.png` });

      const fila = (texto) => [...document.querySelectorAll('tbody tr')].find((tr) => tr.textContent.includes(texto));
      const sinCosto = fila('NOTEBOOK SIN COTIZACION DEL DIA');
      const conCosto = fila('NOTEBOOK CON COSTO SI');
      expect(sinCosto.textContent).toContain('Sin costo');
      const gananciaSinCosto = sinCosto.querySelector('td[title="Sin costo: la ganancia no se puede calcular"]');
      expect(gananciaSinCosto?.textContent).toBe('—');
      expect(sinCosto.textContent).not.toContain('990.000');
      expect(conCosto.textContent).toContain('390.000');
      screen.unmount();
    });
  }
});
