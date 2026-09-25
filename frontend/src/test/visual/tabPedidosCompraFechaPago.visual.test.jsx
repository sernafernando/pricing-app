/**
 * Remediation — painted Proveedor vs Mon. geometry on Pedidos.
 *
 * jsdom runs `css: false`, so TabPedidosCompra.test.jsx can only prove
 * `<col>` style widths. This file is the Chromium close of that PARTIAL:
 * real cell boxes must have positive width and zero overlap.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import TabPedidosCompra from '../../components/compras/TabPedidosCompra';
import api from '../../services/api';

// Browser visual project prebundles a separate React graph if MemoryRouter
// is imported live (Vite reloads + invalid hook call). TabPedidosCompra only
// needs search params; keep the hook isolated from a real router.
vi.mock('react-router-dom', () => ({
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  authAPI: { login: vi.fn(), me: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: ['administracion.gestionar_ordenes_compra'],
    tienePermiso: () => true,
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const isoDaysFromToday = (delta) => {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() + delta);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const PEDIDO_NO_COLLIDE = {
  id: 1,
  numero: 'P-01-2026-00001',
  empresa_id: 1,
  empresa_nombre: 'Empresa Uno',
  proveedor_id: 2,
  proveedor_nombre: 'Proveedor Distribuidora Internacional del Sur S.A.',
  moneda: 'ARS',
  monto: '1000.00',
  estado: 'aprobado',
  eje_procesal: 'por_recibir',
  oc_vinculada: false,
  oc_match_status: null,
  factura_cargada: false,
  tiene_numero_factura: true,
  facturas_documento: 'FA-10',
  fecha_pago_estimada: isoDaysFromToday(3),
  saldo_pendiente: '1000.00',
};

const overlapArea = (a, b) => {
  const w = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
  const h = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  return w * h;
};

const cellByHeader = (container, label) => {
  const headers = [...container.querySelectorAll('th')];
  const index = headers.findIndex((th) => th.textContent.trim() === label);
  if (index < 0) throw new Error(`column header not found: ${label}`);
  const row = container.querySelector('tbody tr');
  if (!row) throw new Error('tbody row not mounted');
  return row.children[index];
};

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((url) => {
    if (url === '/administracion/compras/pedidos') {
      return Promise.resolve({
        data: { items: [PEDIDO_NO_COLLIDE], total: 1, page: 1, page_size: 50 },
      });
    }
    if (url === '/admin/empresas') {
      return Promise.resolve({ data: [] });
    }
    return Promise.resolve({ data: { items: [], total: 0 } });
  });
});

const paintedBox = (el) => {
  const range = document.createRange();
  range.selectNodeContents(el);
  const ink = range.getBoundingClientRect();
  if (ink.width > 0 && ink.height > 0) return ink;
  return el.getBoundingClientRect();
};

describe('TabPedidosCompra — Proveedor vs Mon. layout', () => {
  it('keeps Proveedor and Mon. cells painted with positive width and zero overlap', async () => {
    // Viewport is 1280; specified Pedidos cols already sum ~1322. Give the
    // table the leftover the flexible Proveedor col needs so this is a
    // geometry test, not a "viewport shorter than fixed cols" test.
    const { container } = await render(
      <div style={{ width: '1600px', maxWidth: '1600px' }}>
        <TabPedidosCompra />
      </div>
    );
    await vi.waitFor(() => {
      if (!container.textContent.includes('P-01-2026-00001')) {
        throw new Error('Pedidos row not mounted yet');
      }
    });

    const proveedor = cellByHeader(container, 'Proveedor');
    const moneda = cellByHeader(container, 'Mon.');
    expect(proveedor).toBeTruthy();
    expect(moneda).toBeTruthy();
    expect(proveedor.textContent).toContain(PEDIDO_NO_COLLIDE.proveedor_nombre);
    expect(moneda.textContent).toContain('ARS');

    const proveedorRect = paintedBox(proveedor);
    const monedaRect = paintedBox(moneda);
    expect(proveedorRect.width).toBeGreaterThan(0);
    expect(proveedorRect.height).toBeGreaterThan(0);
    expect(monedaRect.width).toBeGreaterThan(0);
    expect(monedaRect.height).toBeGreaterThan(0);
    expect(overlapArea(proveedorRect, monedaRect)).toBe(0);
    expect(overlapArea(proveedor.getBoundingClientRect(), moneda.getBoundingClientRect())).toBe(0);
  });
});
