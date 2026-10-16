/**
 * The order detail of a `tplink.solo` user: `cadena_total_tp` instead of
 * `cadena_total_gauss` -- the same chain with the TP cost line, ending in
 * Total TP. No Gauss wording anywhere in the panel.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import SaleDetailPanel from './SaleDetailPanel';
import api from '../../services/api';

const detail = (cadena) => ({
  order: { order_id: 2001, pack_id: null },
  items: [],
  shipment: null,
  breakdown: {
    monto_operacion: 1000,
    neto: 800,
    incompleto: false,
    incomplete_reasons: [],
    lines: [{ code: 'comision_ml', concepto: 'Comisión ML', monto: 200, origen: 'api' }],
  },
  iva_decomposicion: { neto_sin_iva: 661.16, componentes: [], razones: [], reconcilia: true },
  total_tp: cadena.total_tp,
  cadena_total_tp: cadena,
});

beforeEach(() => {
  api.get.mockReset();
});

function mockDetail(data) {
  api.get.mockImplementation((url) =>
    Promise.resolve({ data: url === '/ml-ventas-ops/orders/2001' ? data : {} }),
  );
}

describe('SaleDetailPanel, TP chain', () => {
  it('renders the chain with the TP cost and ends in Total TP and Markup TP', async () => {
    mockDetail(
      detail({
        total_tp: 361.16,
        costo_tp: 300,
        markup_tp: 20.4,
        tp_incompleto: false,
        lineas: [{ code: 'costo_tp', monto: 300 }],
        provisional: false,
        provisional_falta: null,
      }),
    );
    render(<SaleDetailPanel orderId={2001} onClose={vi.fn()} />);
    const section = await screen.findByRole('region', { name: 'Total TP' });
    expect(within(section).getByText('Costo TP')).toBeInTheDocument();
    expect(section).toHaveTextContent('361,16');
    expect(section).toHaveTextContent('Markup TP');
    expect(section).toHaveTextContent('20,40%');
    expect(document.body).not.toHaveTextContent(/gauss/i);
  });

  it('shows a dash and "incompleto" when the TP cost is missing, never 0', async () => {
    mockDetail(
      detail({
        total_tp: null,
        costo_tp: null,
        markup_tp: null,
        tp_incompleto: true,
        lineas: [{ code: 'costo_tp', monto: null }],
        provisional: false,
        provisional_falta: null,
      }),
    );
    render(<SaleDetailPanel orderId={2001} onClose={vi.fn()} />);
    const section = await screen.findByRole('region', { name: 'Total TP' });
    expect(section).toHaveTextContent('Total TP incompleto: falta el costo TP.');
    expect(section).not.toHaveTextContent('0,00');
    expect(document.body).not.toHaveTextContent(/gauss/i);
  });

  it('treats a missing total_tp key like null: a dash, never an amount', async () => {
    mockDetail(
      detail({
        costo_tp: null,
        markup_tp: null,
        tp_incompleto: true,
        lineas: [{ code: 'costo_tp', monto: null }],
        provisional: false,
        provisional_falta: null,
      }),
    );
    render(<SaleDetailPanel orderId={2001} onClose={vi.fn()} />);
    const section = await screen.findByRole('region', { name: 'Total TP' });
    expect(section).toHaveTextContent('Total TP incompleto: falta el costo TP.');
    expect(section).not.toHaveTextContent('$ 0,00');
    expect(section).not.toHaveTextContent('NaN');
  });
});
