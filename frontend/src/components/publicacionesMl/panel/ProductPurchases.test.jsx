/**
 * A product's last purchases (publicaciones-ml-paridad-productos S12b), the "Últimas 5 compras" of Productos' info
 * modal (`GET /productos/{id}/detalle`, `ultimas_compras`): date, supplier, quantity, unit price in its currency and
 * total. Only with `productos.ver_info_compras`, as Productos.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductPurchases from './ProductPurchases';
import { productosAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  productosAPI: { detalle: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

let granted = new Set(['productos.ver_info_compras']);
vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });

const compra = (overrides = {}) => ({
  proveedor: 'TP-Link Argentina',
  fecha: '2026-10-14T00:00:00',
  cantidad: 12,
  precio_unitario: 45.5,
  moneda_id: 2,
  ...overrides,
});

const detail = (ultimas_compras) => ({ data: { producto: { item_id: 4101 }, ultimas_compras } });

const renderPurchases = () => render(<ProductPurchases productItemId={4101} />);

beforeEach(() => {
  granted = new Set(['productos.ver_info_compras']);
  productosAPI.detalle.mockReset();
  productosAPI.detalle.mockResolvedValue(detail([compra(), compra({ proveedor: 'Otro', moneda_id: 1, precio_unitario: 98500, cantidad: 1.5 })]));
});

describe('each purchase', () => {
  it('says when, from whom, how many, at what unit price in its currency and the total', async () => {
    renderPurchases();
    const [first, second] = await screen.findAllByRole('listitem');

    expect(productosAPI.detalle).toHaveBeenCalledWith(4101);
    expect(first).toHaveTextContent('14/10/2026');
    expect(first).toHaveTextContent('TP-Link Argentina');
    expect(first).toHaveTextContent('12 u.');
    expect(first).toHaveTextContent('USD 45,50');
    expect(first).toHaveTextContent('USD 546,00');
    expect(second).toHaveTextContent('1,5 u.');
    expect(second).toHaveTextContent('ARS 98.500,00');
    expect(second).toHaveTextContent('ARS 147.750,00');
  });

  it('an unknown currency or missing supplier and date say so, never a bare code', async () => {
    productosAPI.detalle.mockResolvedValue(detail([compra({ moneda_id: 7, proveedor: null, fecha: null })]));
    renderPurchases();
    const item = await screen.findByRole('listitem');
    expect(item).toHaveTextContent('Sin proveedor');
    expect(item).toHaveTextContent('Sin fecha');
    expect(item).toHaveTextContent('45,50 (moneda sin identificar)');
  });

  it('a missing quantity or unit price says so, never a zero nor a total', async () => {
    productosAPI.detalle.mockResolvedValue(
      detail([compra({ cantidad: null }), compra({ proveedor: 'Otro', precio_unitario: null })]),
    );
    renderPurchases();
    const [noQuantity, noPrice] = await screen.findAllByRole('listitem');
    expect(noQuantity).toHaveTextContent('Cantidad sin dato × USD 45,50');
    expect(noPrice).toHaveTextContent('12 u. × precio sin dato');
    for (const item of [noQuantity, noPrice]) {
      expect(item).not.toHaveTextContent('=');
      expect(item).not.toHaveTextContent('0,00');
    }
  });
});

describe('the section', () => {
  it('without productos.ver_info_compras shows nothing and reads nothing', () => {
    granted = new Set();
    const { container } = renderPurchases();
    expect(container).toBeEmptyDOMElement();
    expect(productosAPI.detalle).not.toHaveBeenCalled();
  });

  it('says so when the product has no purchase', async () => {
    productosAPI.detalle.mockResolvedValue(detail([]));
    renderPurchases();
    expect(await screen.findByText('No hay compras registradas para este producto.')).toBeInTheDocument();
  });

  it('a failure says so and retries', async () => {
    productosAPI.detalle.mockRejectedValueOnce(httpError(500));
    const user = userEvent.setup();
    renderPurchases();
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar las últimas compras.');
    await user.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findAllByRole('listitem')).toHaveLength(2);
  });
});
