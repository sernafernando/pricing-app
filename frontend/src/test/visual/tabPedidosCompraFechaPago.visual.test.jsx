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

const TWO_WORD_EMPRESA = 'Holding Norte';
const SHORT_EMPRESA = 'Acme';
const LONG_EMPRESA =
  'Empresa Comercializadora Internacional del Sur Sociedad Anonima Limitada Extra Larga';

const PEDIDOS = [
  {
    ...PEDIDO_BASE,
    id: 1,
    numero: 'P-01-2026-00001',
    empresa_nombre: TWO_WORD_EMPRESA,
  },
  {
    ...PEDIDO_BASE,
    id: 2,
    numero: 'P-01-2026-00002',
    empresa_nombre: SHORT_EMPRESA,
  },
  {
    ...PEDIDO_BASE,
    id: 3,
    numero: 'P-01-2026-00003',
    empresa_nombre: LONG_EMPRESA,
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
        data: { items: PEDIDOS, total: PEDIDOS.length, page: 1, page_size: 50 },
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

const empresaInner = (cell) => cell.querySelector('[data-testid="empresa-cell"]') || cell;

const assertLockedEmpresaStyle = (inner) => {
  const style = getComputedStyle(inner);
  expect(style.display).toBe('block');
  expect(style.textAlign).toBe('center');
  expect(style.whiteSpace).toBe('normal');
  expect(style.overflowWrap).toBe('anywhere');
  expect(style.overflow).toBe('hidden');
  expect(style.textOverflow).not.toBe('ellipsis');
  const fontSize = Number.parseFloat(style.fontSize);
  expect(Number.parseFloat(style.lineHeight) / fontSize).toBeCloseTo(1.25, 2);
  expect(Number.parseFloat(style.maxHeight) / fontSize).toBeCloseTo(2.5, 2);
  expect(inner.getAttribute('data-wrap')).toBeNull();
  expect(inner.querySelector('br')).toBeNull();
};

const assertNoEllipsis = (el) => {
  const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
  expect(text).not.toContain('…');
  expect(text).not.toMatch(/\.\.\./);
};

const assertTwoLineClipBudget = (inner) => {
  const style = getComputedStyle(inner);
  const maxHeight = Number.parseFloat(style.maxHeight);
  expect(inner.getBoundingClientRect().height).toBeLessThanOrEqual(maxHeight + 1);
  expect(inner.clientHeight).toBeLessThanOrEqual(maxHeight + 1);
};

describe('TabPedidosCompra — layout at 1280–1400', () => {
  it('clips Empresa at two generic lines, 2-col Acciones, and zero Proveedor/Mon overlap', async () => {
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
        throw new Error('Short-name row not mounted yet');
      }
      if (!container.textContent.includes('P-01-2026-00003')) {
        throw new Error('Long-name row not mounted yet');
      }
    });

    const empresaCells = cellsByHeader(container, 'Empresa');
    const proveedorCells = cellsByHeader(container, 'Proveedor');
    expect(empresaCells).toHaveLength(3);

    const inners = empresaCells.map(empresaInner);
    for (const inner of inners) {
      assertLockedEmpresaStyle(inner);
      assertNoEllipsis(inner);
      assertTwoLineClipBudget(inner);
      expect(inner.scrollWidth).toBeLessThanOrEqual(inner.clientWidth + 1);
    }

    const twoWord = inners[0];
    const twoWordStyle = getComputedStyle(twoWord);
    const twoWordLine = Number.parseFloat(twoWordStyle.lineHeight);
    expect(twoWord.textContent).toContain('Holding');
    expect(twoWord.textContent).toContain('Norte');
    expect(twoWord.getBoundingClientRect().height).toBeGreaterThan(twoWordLine * 1.15);
    expect(twoWord.scrollHeight).toBeLessThanOrEqual(twoWord.clientHeight + 1);

    const shortName = inners[1];
    const shortLine = Number.parseFloat(getComputedStyle(shortName).lineHeight);
    expect(shortName.textContent.trim()).toBe(SHORT_EMPRESA);
    expect(shortName.getBoundingClientRect().height).toBeLessThanOrEqual(shortLine * 1.2 + 1);

    const longName = inners[2];
    expect(longName.scrollHeight).toBeGreaterThan(longName.clientHeight);
    expect(overlapArea(longName.getBoundingClientRect(), proveedorCells[2].getBoundingClientRect())).toBe(0);
    expect(overlapArea(empresaCells[2].getBoundingClientRect(), proveedorCells[2].getBoundingClientRect())).toBe(0);

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
