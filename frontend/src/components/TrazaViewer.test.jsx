import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import TrazaViewer from './TrazaViewer';

// The ML trace (GET /seriales/traza/ml) lists the stored ML orders no ERP order stands for with soh_id 0, e.g. the
// orders of a pack known only to Ventas ML. Such an order reads as its ML sale, never as "pedido #0".

const pedido = (sohId, mlId, braId = 0) => ({
  soh_id: sohId,
  bra_id: braId,
  fecha: '2026-11-07 14:30:00+00:00',
  estado: 'paid',
  cliente: 'COMPRADORPRUEBA',
  ml_id: mlId,
  shipping_id: 40000000101,
});

const producto = (itemId, codigo) => ({
  serial: '',
  articulo: { item_id: itemId, codigo, descripcion: `Cartucho ${codigo}` },
  movimientos: [],
  rma: [],
  cantidad: 1,
});

const traza = {
  ml_id: '2000000000000101',
  busqueda_por: 'ventas_ml',
  pedidos: [pedido(0, '2000000000000102'), pedido(0, '2000000000000103'), pedido(32001, '2000000000000104', 45)],
  seriales: [producto(601, 'CART-NEGRO'), producto(602, 'CART-COLOR')],
  rma_por_factura: [],
  claims: [],
};

afterEach(() => vi.restoreAllMocks());

describe('TrazaViewer - ML trace orders', () => {
  it('shows a stored ML order without ERP order as its ML sale, not as #0', () => {
    render(<TrazaViewer data={traza} variant="ml" />);

    expect(screen.queryByText('#0')).toBeNull();
    expect(screen.getByText('Venta ML #2000000000000102')).toBeInTheDocument();
    expect(screen.getByText('Venta ML #2000000000000103')).toBeInTheDocument();
  });

  it('keeps showing the ERP order number when there is one', () => {
    render(<TrazaViewer data={traza} variant="ml" />);

    expect(screen.getByText('#32001')).toBeInTheDocument();
  });

  it('renders every order and product with a unique key', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(<TrazaViewer data={traza} variant="ml" />);

    const duplicados = error.mock.calls.filter((args) => String(args[0]).includes('same key'));
    expect(duplicados).toEqual([]);
  });
});
