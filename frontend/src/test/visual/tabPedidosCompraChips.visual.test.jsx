/**
 * Phase 6 — painted Proceso chips + Con faltantes vs Proceso geometry.
 *
 * jsdom runs `css: false`, so TabPedidosCompra.test.jsx can only prove
 * `data-tone` / `data-layout`. This file is the Chromium close of that
 * PARTIAL: resolved colors (token-aligned) and real boxes.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from 'vitest-browser-react';
import { tokenColor, setTheme } from './visualHelpers';
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

const PEDIDO_CHIPS = {
  id: 1,
  numero: 'P-01-2026-00001',
  empresa_id: 1,
  empresa_nombre: 'Empresa Uno',
  proveedor_id: 2,
  proveedor_nombre: 'Proveedor Uno',
  moneda: 'ARS',
  monto: '1000.00',
  estado: 'con_faltantes',
  eje_procesal: 'por_recibir',
  oc_vinculada: true,
  oc_match_status: 'error',
  factura_cargada: true,
  tiene_numero_factura: true,
  facturas_documento: 'FA-10',
  ocs: [{ oc_comp_id: 1, oc_bra_id: 1, oc_poh_id: 100 }],
  saldo_pendiente: '1000.00',
};

const PEDIDO_NUMERO = {
  ...PEDIDO_CHIPS,
  id: 2,
  numero: 'P-01-2026-00002',
  estado: 'aprobado',
  eje_procesal: 'por_recibir',
  oc_vinculada: false,
  oc_match_status: null,
  factura_cargada: false,
  tiene_numero_factura: true,
  ocs: [],
};

const overlapArea = (a, b) => {
  const w = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
  const h = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  return w * h;
};

beforeEach(() => {
  vi.clearAllMocks();
  setTheme('light');
  api.get.mockImplementation((url) => {
    if (url === '/administracion/compras/pedidos') {
      return Promise.resolve({
        data: { items: [PEDIDO_CHIPS, PEDIDO_NUMERO], total: 2, page: 1, page_size: 50 },
      });
    }
    if (url === '/admin/empresas') {
      return Promise.resolve({ data: [] });
    }
    return Promise.resolve({ data: { items: [], total: 0 } });
  });
});

async function renderTab() {
  const { container } = await render(<TabPedidosCompra />);
  await vi.waitFor(() => {
    if (!container.querySelector('[data-testid="chip-oc"]')) {
      throw new Error('Proceso chips not mounted yet');
    }
  });
  return container;
}

describe('TabPedidosCompra — painted Proceso chip colors', () => {
  it('paints OC/Factura/Match-error as distinct token colors, not muted gray', async () => {
    const container = await renderTab();
    const oc = container.querySelector('[data-testid="chip-oc"]');
    const factura = container.querySelector('[data-testid="chip-factura-cargada"]');
    const match = container.querySelector('[data-testid="chip-match-error"]');
    const numero = container.querySelector('[data-testid="chip-numero-factura"]');

    expect(oc).toBeTruthy();
    expect(factura).toBeTruthy();
    expect(match).toBeTruthy();
    expect(numero).toBeTruthy();

    for (const theme of ['light', 'dark']) {
      setTheme(theme);
      const ocColor = getComputedStyle(oc).color;
      const facturaColor = getComputedStyle(factura).color;
      const matchColor = getComputedStyle(match).color;
      const numeroColor = getComputedStyle(numero).color;
      const muted = tokenColor('--cf-text-tertiary');

      expect(ocColor).toBe(tokenColor('--cf-accent-blue'));
      expect(facturaColor).toBe(tokenColor('--cf-accent-green'));
      expect(matchColor).toBe(tokenColor('--cf-danger'));

      expect(new Set([ocColor, facturaColor, matchColor]).size).toBe(3);
      expect(facturaColor).not.toBe(matchColor);
      expect(ocColor).not.toBe(muted);
      expect(facturaColor).not.toBe(muted);
      expect(matchColor).not.toBe(muted);
      expect(facturaColor).not.toBe(numeroColor);
      expect(matchColor).not.toBe(numeroColor);
      expect(ocColor).not.toBe(numeroColor);
    }
  });
});

describe('TabPedidosCompra — Con faltantes vs Proceso layout', () => {
  it('keeps the Con faltantes badge visible and not covered by Proceso', async () => {
    const container = await renderTab();
    const estado = container.querySelector('[data-testid="estado-cell"]');
    const proceso = container.querySelector('[data-testid="proceso-cell"]');
    expect(estado).toBeTruthy();
    expect(proceso).toBeTruthy();
    expect(estado.textContent).toMatch(/con faltantes/i);

    const estadoCs = getComputedStyle(estado);
    const procesoCs = getComputedStyle(proceso);
    const estadoZ = Number.parseInt(estadoCs.zIndex, 10);
    const procesoZ = Number.parseInt(procesoCs.zIndex, 10);

    expect(estadoCs.overflow).toBe('visible');
    expect(procesoCs.overflow).toBe('visible');
    expect(estadoZ).toBeGreaterThan(procesoZ);

    const badge = estado.querySelector('span');
    expect(badge).toBeTruthy();
    const badgeRect = badge.getBoundingClientRect();
    const procesoRect = proceso.getBoundingClientRect();
    expect(badgeRect.width).toBeGreaterThan(0);
    expect(badgeRect.height).toBeGreaterThan(0);
    expect(overlapArea(badgeRect, procesoRect)).toBe(0);
  });
});
