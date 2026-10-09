/**
 * Drift guard: the screen catalog is a hand-written mirror of App.jsx's
 * `protectedRoutes` (permissions) and Sidebar.jsx's `menuSections` (labels and
 * sections). Neither file exports its table, so the contract is read from the
 * sources (same approach as App.publicacionesMlRoute.test.js).
 */
import { describe, it, expect } from 'vitest';
import appSource from '../App.jsx?raw';
import sidebarSource from '../components/Sidebar.jsx?raw';
import {
  SCREENS,
  EXCLUDED_ROUTES,
  CATEGORIAS_PERMISO,
  nombreCategoria,
} from './screenCatalog';

function parseProtectedRoutes(source) {
  const start = source.indexOf('const protectedRoutes = [');
  const end = source.indexOf('\n];', start);
  expect(start).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(start);
  const block = source.slice(start, end);

  const routes = [];
  for (const match of block.matchAll(/\{\s*path:\s*'([^']+)'([^{}]*)\}/g)) {
    const [, path, body] = match;
    const single = body.match(/permiso:\s*'([^']+)'/);
    const multiple = body.match(/permisos:\s*\[([^\]]*)\]/);
    const permisos = multiple
      ? [...multiple[1].matchAll(/'([^']+)'/g)].map((m) => m[1])
      : single
        ? [single[1]]
        : [];
    routes.push({ path, permisos });
  }
  return routes;
}

function parseSidebar(source) {
  const items = [];
  let section = null;
  for (const line of source.split('\n')) {
    const title = line.match(/^\s*title:\s*'([^']+)'/);
    if (title) section = title[1];
    const item = line.match(/\{\s*label:\s*'([^']+)',\s*path:\s*'([^']+)'/);
    if (item) items.push({ label: item[1], path: item[2], section });
  }
  // Multi-line items (`label:` and `path:` on separate lines).
  for (const match of source.matchAll(/label:\s*'([^']+)',\s*\n\s*path:\s*'([^']+)'/g)) {
    items.push({ label: match[1], path: match[2], section: null });
  }
  return items;
}

const appRoutes = parseProtectedRoutes(appSource);
const byPath = new Map(SCREENS.map((s) => [s.path, s]));

describe('screen catalog vs App.jsx protectedRoutes', () => {
  it('parses a realistic number of protected routes', () => {
    expect(appRoutes.length).toBeGreaterThan(50);
    expect(appRoutes.find((r) => r.path === '/administracion/compras').permisos).toHaveLength(5);
  });

  it('has an entry for every protected route with the same permission set', () => {
    for (const route of appRoutes) {
      if (EXCLUDED_ROUTES.includes(route.path)) continue;
      const screen = byPath.get(route.path);
      expect(screen, `missing catalog entry for ${route.path}`).toBeDefined();
      expect([...screen.permisos].sort(), `permissions drifted for ${route.path}`).toEqual(
        [...route.permisos].sort(),
      );
    }
  });

  it('only lists paths that exist in App.jsx', () => {
    const appPaths = new Set(appRoutes.map((r) => r.path));
    for (const screen of SCREENS) {
      expect(appPaths.has(screen.path), `${screen.path} is not a route in App.jsx`).toBe(true);
    }
  });

  it('keeps excluded routes real, so the exclusion list cannot rot', () => {
    const appPaths = new Set(appRoutes.map((r) => r.path));
    for (const path of EXCLUDED_ROUTES) {
      expect(appPaths.has(path), `${path} no longer exists; drop it from EXCLUDED_ROUTES`).toBe(true);
      expect(byPath.has(path)).toBe(false);
    }
  });

  it('has no duplicated paths', () => {
    expect(byPath.size).toBe(SCREENS.length);
  });
});

describe('screen catalog vs Sidebar.jsx menuSections', () => {
  const sidebarItems = parseSidebar(sidebarSource);

  it('includes every sidebar item under the same section', () => {
    expect(sidebarItems.length).toBeGreaterThan(40);
    for (const item of sidebarItems) {
      const screen = byPath.get(item.path);
      expect(screen, `sidebar item ${item.path} missing from catalog`).toBeDefined();
      expect(screen.label).toBe(item.label);
      if (item.section) expect(screen.section).toBe(item.section);
    }
  });
});

describe('screen catalog shape', () => {
  it('uses a valid scope, and public screens need no permission', () => {
    for (const screen of SCREENS) {
      expect(['permiso', 'data', 'public']).toContain(screen.scope);
      expect(screen.scope === 'public').toBe(screen.permisos.length === 0);
    }
  });

  it('marks the pm_scope-filtered screens as data-scoped', () => {
    const dataPaths = SCREENS.filter((s) => s.scope === 'data').map((s) => s.path).sort();
    expect(dataPaths).toEqual(['/consultas/ranking', '/dashboard-metricas-ml', '/metricas-ml']);
  });
});

describe('permission category labels', () => {
  it('labels every backend category', () => {
    for (const categoria of [
      'productos', 'ventas_ml', 'ventas_fuera', 'ventas_tn', 'clientes', 'administracion', 'reportes',
      'configuracion', 'alertas', 'envios_flex', 'rrhh', 'tickets', 'documentos', 'administracion_sector',
      'rma', 'ml_ops', 'consultas', 'promos', 'pxq', 'deposito_sector', 'tesoreria', 'etiquetas',
    ]) {
      expect(CATEGORIAS_PERMISO[categoria], categoria).toBeTruthy();
    }
  });

  it('humanizes unknown categories', () => {
    expect(nombreCategoria('ventas_ml')).toBe('Ventas MercadoLibre');
    expect(nombreCategoria('nueva_area_x')).toBe('Nueva area x');
    expect(nombreCategoria('')).toBe('Sin categoría');
  });
});
