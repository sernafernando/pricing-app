import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../../services/api';
import ModalPedidoDetalle from './ModalPedidoDetalle';

// NOTE: vite.config.js sets `css: false` for the test run, so CSS Module class
// names do NOT resolve. Never assert on className — assert on text, roles, testids.

const FACTURA_ROW = {
  id: 10,
  pedido_id: 1,
  numero: 'FA-10',
  created_at: '2026-09-23T12:00:00Z',
  created_by_id: 1,
  cargada: false,
  cargada_marked_at: null,
  cargada_marked_by_id: null,
};

const PEDIDO_BASE = {
  id: 1,
  numero: 'P-01-2026-00001',
  estado: 'aprobado',
  empresa_id: 1,
  empresa_nombre: 'Empresa Uno',
  proveedor_id: 2,
  proveedor_nombre: 'Proveedor Uno',
  moneda: 'ARS',
  monto: '1000.00',
  oc_vinculada: false,
  oc_poh_id: null,
  oc_match_status: null,
  factura_cargada: false,
  tiene_numero_factura: true,
  factura_documentos: [FACTURA_ROW],
  facturas_documento: 'FA-10; FA-99-BLOB',
  pedidos_documento: 'NV-1',
  numero_factura: null,
  imputaciones: [],
  eventos: [],
};

function mockPedido(pedido) {
  api.get.mockImplementation((url) => {
    if (url === `/administracion/compras/pedidos/${pedido.id}`) {
      return Promise.resolve({ data: pedido });
    }
    return Promise.resolve({ data: [] });
  });
}

async function renderDetalle(pedido) {
  mockPedido(pedido);
  render(<ModalPedidoDetalle pedidoId={pedido.id} onClose={() => {}} />);
  await screen.findByText(`Pedido ${pedido.numero}`);
}

describe('ModalPedidoDetalle — constancia vs cargada ERP', () => {
  it('chip-off-with-numbers: shows constancia + unchecked ERP box; blob is not cargada', async () => {
    await renderDetalle(PEDIDO_BASE);

    expect(screen.getByText('FA-10')).toBeInTheDocument();
    const checkbox = screen.getByRole('checkbox', { name: 'Cargada en ERP FA-10' });
    expect(checkbox).not.toBeChecked();
    expect(screen.queryByTestId('chip-factura-cargada')).not.toBeInTheDocument();
    expect(screen.getByTestId('chip-numero-factura')).toHaveTextContent('Número');
    expect(screen.queryByText('FA-99-BLOB')).not.toBeInTheDocument();
    expect(screen.getByText('NV-1')).toBeInTheDocument();
    expect(
      screen.queryByRole('checkbox', { name: /NV-1|Pedido/i })
    ).not.toBeInTheDocument();
  });

  it('does not treat leftover facturas_documento text as cargada or as a checkbox', async () => {
    await renderDetalle({
      ...PEDIDO_BASE,
      tiene_numero_factura: false,
      factura_documentos: [],
      facturas_documento: 'FA-BLOB-ONLY',
    });

    expect(screen.getByText('FA-BLOB-ONLY')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /Cargada en ERP/ })).not.toBeInTheDocument();
    expect(screen.queryByTestId('chip-factura-cargada')).not.toBeInTheDocument();
    expect(screen.queryByTestId('chip-numero-factura')).not.toBeInTheDocument();
  });

  it('chip-on-after-check: PATCH {cargada:true} lights the Factura chip', async () => {
    const user = userEvent.setup();
    api.patch.mockResolvedValue({
      data: {
        ...FACTURA_ROW,
        cargada: true,
        cargada_marked_at: '2026-09-23T12:05:00Z',
        cargada_marked_by_id: 1,
      },
    });
    await renderDetalle(PEDIDO_BASE);

    await user.click(screen.getByRole('checkbox', { name: 'Cargada en ERP FA-10' }));

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        '/administracion/compras/pedidos/1/factura-documentos/10',
        { cargada: true }
      );
    });
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: 'Cargada en ERP FA-10' })).toBeChecked();
      expect(screen.getByTestId('chip-factura-cargada')).toHaveTextContent('Factura');
    });
    expect(screen.queryByTestId('chip-numero-factura')).not.toBeInTheDocument();
  });
});
