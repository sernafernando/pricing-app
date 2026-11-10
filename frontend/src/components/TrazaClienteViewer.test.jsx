import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import TrazaClienteViewer from './TrazaClienteViewer';

// Customer trace orders: an order without ERP order (soh_id 0) reads as its ML sale, and orders are keyed and
// expanded one by one even when two share soh_id (order numbers repeat across branches).

const pedido = (sohId, braId, mlId, codigo) => ({
  soh_id: sohId,
  bra_id: braId,
  fecha: '2026-11-07',
  estado: 'Facturado',
  total: 1000,
  ml_id: mlId,
  lineas: [{ sod_id: `${braId}-${sohId}`, item_code: codigo, seriales: [] }],
});

const data = {
  cliente: { cust_id: 1, nombre: 'Cliente de prueba' },
  transacciones: [],
  total_transacciones: 0,
  pedidos: [
    pedido(0, 0, '2000000000000102', 'CART-NEGRO'),
    pedido(31000, 45, null, 'ROUTER-A'),
    pedido(31000, 46, null, 'ROUTER-B'),
  ],
  rmas_erp: [],
  rmas_internos: [],
};

afterEach(() => vi.restoreAllMocks());

describe('TrazaClienteViewer - orders', () => {
  it('shows an order without ERP order as its ML sale, not as #0', () => {
    render(<TrazaClienteViewer data={data} />);

    expect(screen.queryByText('#0')).toBeNull();
    expect(screen.getByText('Venta ML #2000000000000102')).toBeInTheDocument();
  });

  it('expands only the clicked order when two orders share their number', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<TrazaClienteViewer data={data} />);

    fireEvent.click(screen.getAllByText('#31000')[0]);

    expect(screen.getByText('ROUTER-A')).toBeInTheDocument();
    expect(screen.queryByText('ROUTER-B')).toBeNull();
    expect(error.mock.calls.filter((args) => String(args[0]).includes('same key'))).toEqual([]);
  });
});
