/**
 * ODD `vpf-metricas-canal-fe` S4/S5/C4: the routes behind "ventas por fuera". `App.jsx` keeps its route table
 * private, so the contract is read from its source (same approach as App.publicacionesMlRoute.test.js).
 */
import { describe, it, expect } from 'vitest';
import appSource from './App.jsx?raw';

describe('Ventas por fuera routes', () => {
  it('S5: /metricas-ml opens with ml_metricas.ver OR ventas_fuera.ver_metricas_pdf', () => {
    expect(appSource).toMatch(
      /\{ path: '\/metricas-ml', component: MetricasML, permisos: \['ml_metricas\.ver', 'ventas_fuera\.ver_metricas_pdf'\] \}/,
    );
  });

  it('C4: the upload history /metricas-ml/cargas opens with subir_pdf OR ver_metricas_pdf', () => {
    expect(appSource).toMatch(
      /\{ path: '\/metricas-ml\/cargas', component: CargasPdf, permisos: \['ventas_fuera\.subir_pdf', 'ventas_fuera\.ver_metricas_pdf'\] \}/,
    );
    expect(appSource).toMatch(/CargasPdf = lazy\(\(\) => import\('\.\/pages\/CargasPdf'\)\)/);
  });

  it('vpf-operaciones S4: the old dashboard is back on /dashboard-ventas-fuera with ver_dashboard, no redirect', () => {
    expect(appSource).toMatch(
      /\{ path: '\/dashboard-ventas-fuera', component: DashboardVentasFuera, permiso: 'ventas_fuera\.ver_dashboard' \}/,
    );
    expect(appSource).toMatch(/DashboardVentasFuera = lazy\(\(\) => import\('\.\/pages\/DashboardVentasFuera'\)\)/);
    expect(appSource).not.toMatch(/<Navigate to="\/metricas-ml\?canal=fuera"/);
  });

  it('S4: the excluded-salespeople admin keeps its own route with the old tab permission', () => {
    expect(appSource).toMatch(
      /\{ path: '\/dashboard-ventas-fuera\/vendedores-excluidos', component: VendedoresExcluidos, permiso: 'ventas_fuera\.ver_dashboard' \}/,
    );
  });

  it('keeps the other Reportes routes as they were', () => {
    expect(appSource).toMatch(/\{ path: '\/ml-ads-aportes', component: MlAds, permiso: 'ml_metricas\.ver' \}/);
    expect(appSource).toMatch(/\{ path: '\/dashboard-tienda-nube', component: DashboardTiendaNube, permiso: 'ventas_tn\.ver_dashboard' \}/);
  });
});
