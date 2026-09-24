/**
 * Pedidos layout geometry at 1280–1400 useful table width.
 *
 * jsdom runs `css: false`, so TabPedidosCompra.test.jsx can only prove
 * `<col>` style widths. Chromium closes Empresa wrap, Acciones 2-col,
 * and Proveedor/Mon. zero overlap.
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

const PEDIDO_BASE = {
  empresa_id: 1,
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

const PEDIDOS = [
  {
    ...PEDIDO_BASE,
    id: 1,
    numero: 'P-01-2026-00001',
    empresa_nombre: 'Grupo Gauss',
  },
  {
    ...PEDIDO_BASE,
    id: 2,
    numero: 'P-01-2026-00002',
    empresa_nombre: 'Pastoriza',
  },
];

const overlapArea = (a, b) => {
  const w = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
  const h = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  return w * h;
};

const cellsByHeader = (container, label) => {
  const headers = [...container.querySelectorAll('th')];
  const index = headers.findIndex((th) => th.textContent.trim() === label);
  if (index < 0) throw new Error(`column header not found: ${label}`);
  const rows = [...container.querySelectorAll('tbody tr')];
  if (rows.length === 0) throw new Error('tbody row not mounted');
  return rows.map((row) => row.children[index]);
};

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((url) => {
    if (url === '/administracion/compras/pedidos') {
      return Promise.resolve({
        data: { items: PEDIDOS, total: 2, page: 1, page_size: 50 },
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

const assertEmpresaFull = (cell, name) => {
  expect(cell.textContent).toContain(name);
  expect(cell.textContent).not.toContain('…');
  expect(cell.textContent).not.toMatch(/\.\.\./);
  const inner = cell.querySelector('[data-testid="empresa-cell"]') || cell;
  const style = getComputedStyle(inner);
  expect(style.textOverflow).not.toBe('ellipsis');
  expect(style.textAlign).toBe('center');
  expect(inner.scrollWidth).toBeLessThanOrEqual(inner.clientWidth + 1);
};

describe('TabPedidosCompra — layout at 1280–1400', () => {
  it('shows full Empresa names, 2-col Acciones, and zero Proveedor/Mon overlap', async () => {
    const { container } = await render(
      <div style={{ width: '1360px', maxWidth: '1360px' }}>
        <TabPedidosCompra />
      </div>
    );
    await vi.waitFor(() => {
      if (!container.textContent.includes('P-01-2026-00001')) {
        throw new Error('Pedidos row not mounted yet');
      }
      if (!container.textContent.includes('P-01-2026-00002')) {
        throw new Error('Pastoriza row not mounted yet');
      }
    });

    const empresaCells = cellsByHeader(container, 'Empresa');
    expect(empresaCells).toHaveLength(2);
    assertEmpresaFull(empresaCells[0], 'Grupo Gauss');
    expect(empresaCells[0].textContent).toContain('Grupo');
    expect(empresaCells[0].textContent).toContain('Gauss');
    assertEmpresaFull(empresaCells[1], 'Pastoriza');

    const grids = [...container.querySelectorAll('[data-testid="row-actions"]')];
    expect(grids.length).toBeGreaterThanOrEqual(1);
    const grid = grids[0];
    expect(getComputedStyle(grid).display).toBe('grid');
    const buttons = [...grid.querySelectorAll('button')];
    expect(buttons.length).toBeGreaterThanOrEqual(4);
    const columnLefts = [
      ...new Set(buttons.map((btn) => Math.round(btn.getBoundingClientRect().left / 4) * 4)),
    ];
    expect(columnLefts).toHaveLength(2);

    const proveedor = cellsByHeader(container, 'Proveedor')[0];
    const moneda = cellsByHeader(container, 'Mon.')[0];
    expect(proveedor.textContent).toContain(PEDIDO_BASE.proveedor_nombre);
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
