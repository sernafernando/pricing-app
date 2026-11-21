/**
 * Dashboard Métricas ML, Detalle de Operaciones — a sale without a known cost (costo SI interface §7: the backend
 * returns a null cost, costo total and markup) reads "sin costo" ("—", secondary text) in its three cells instead of
 * $0 / 0.00 %, at 1440 next to the expanded sidebar, in both themes. With `VITE_DASHBOARD_ML_SHOTS_DIR` it also takes
 * the review screenshots:
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
  descripcion: `Cámara Demo ${codigo}`,
  marca: 'MARCA DEMO',
  categoria: 'CAMARAS',
  cantidad: '1',
  monto_unitario: '100000',
  monto_total: '100000',
  iva: '21',
  pricelist_id: 4,
  tipo_publicacion: 'Clásica',
  costo_sin_iva: costo,
  costo_total: costo,
  comision_porcentaje: '12',
  comision_pesos: '12000',
  costo_envio: '1500',
  monto_limpio: '80000',
  markup_porcentaje: costo === null ? null : '220',
  offset_flex: '0',
  is_cancelled: false,
});

const OPERACIONES = [operacion(1, 'SINCOSTO', null), operacion(2, 'CONCOSTO', '25000')];

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
    await expect.element(conCosto.getByText('220.00%')).toBeVisible();
    expect(conCosto.getByLabelText('Sin costo').elements()).toHaveLength(0);

    await shot(`dashboard-ml-operaciones-sin-costo-1440-${theme}`);
  });
});
