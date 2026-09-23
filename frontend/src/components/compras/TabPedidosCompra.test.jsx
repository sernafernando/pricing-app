import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import api from '../../services/api';
import TabPedidosCompra from './TabPedidosCompra';

// NOTE: vite.config.js sets `css: false` for the test run, so CSS Module class
// names do NOT resolve. Never assert on className — assert on text, roles, testids.

const PEDIDO_CON_NUMERO = {
  id: 1,
  numero: 'P-01-2026-00001',
  empresa_id: 1,
  empresa_nombre: 'Empresa Uno',
  proveedor_id: 2,
  proveedor_nombre: 'Proveedor Uno',
  moneda: 'ARS',
  monto: '1000.00',
  estado: 'aprobado',
  eje_procesal: 'por_recibir',
  oc_vinculada: false,
  oc_match_status: null,
  factura_cargada: false,
  tiene_numero_factura: true,
  facturas_documento: 'FA-10',
  saldo_pendiente: '1000.00',
};

function renderTab(pedido) {
  api.get.mockImplementation((url) => {
    if (url === '/administracion/compras/pedidos') {
      return Promise.resolve({
        data: { items: [pedido], total: 1, page: 1, page_size: 50 },
      });
    }
    if (url === '/admin/empresas') {
      return Promise.resolve({ data: [] });
    }
    return Promise.resolve({ data: {} });
  });
  return render(
    <MemoryRouter>
      <TabPedidosCompra />
    </MemoryRouter>
  );
}

describe('TabPedidosCompra — Factura chip from ERP cargada', () => {
  it('chip-off-with-numbers: muted Número only; Factura chip stays off', async () => {
    renderTab(PEDIDO_CON_NUMERO);

    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(screen.getByTestId('chip-numero-factura')).toHaveTextContent('Número');
    expect(screen.queryByTestId('chip-factura-cargada')).not.toBeInTheDocument();
  });

  it('chip-on-after-check: Factura chip follows factura_cargada, not mere numbers', async () => {
    renderTab({
      ...PEDIDO_CON_NUMERO,
      factura_cargada: true,
      tiene_numero_factura: true,
    });

    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(screen.getByTestId('chip-factura-cargada')).toHaveTextContent('Factura');
    expect(screen.queryByTestId('chip-numero-factura')).not.toBeInTheDocument();
  });
});

describe('TabPedidosCompra — eje procesal label', () => {
  it('labels faltantes_con_res as Faltantes con resolución', async () => {
    renderTab({
      ...PEDIDO_CON_NUMERO,
      estado: 'con_faltantes',
      eje_procesal: 'faltantes_con_res',
    });

    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(screen.getByText('Faltantes con resolución')).toBeInTheDocument();
    expect(screen.queryByText('Faltantes resueltos')).not.toBeInTheDocument();
  });
});

describe('TabPedidosCompra — OC chip is vinculación', () => {
  it('shows compact #poh labels when ocs.length > 1 and no GBP chip', async () => {
    renderTab({
      ...PEDIDO_CON_NUMERO,
      oc_vinculada: true,
      ocs: [
        { oc_comp_id: 1, oc_bra_id: 1, oc_poh_id: 100 },
        { oc_comp_id: 1, oc_bra_id: 1, oc_poh_id: 200 },
      ],
    });

    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(screen.getByTestId('chip-oc')).toHaveTextContent('OC');
    const labels = screen.getAllByTestId('oc-poh-label');
    expect(labels.map((el) => el.textContent)).toEqual(['#100', '#200']);
    expect(screen.queryByText(/existe en GBP/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId('chip-gbp')).not.toBeInTheDocument();
  });

  it('keeps a single OC chip when ocs.length is 1', async () => {
    renderTab({
      ...PEDIDO_CON_NUMERO,
      oc_vinculada: true,
      ocs: [{ oc_comp_id: 1, oc_bra_id: 1, oc_poh_id: 100 }],
    });

    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(screen.getByTestId('chip-oc')).toHaveTextContent('OC');
    expect(screen.queryByTestId('oc-poh-label')).not.toBeInTheDocument();
    expect(screen.queryByText('#100')).not.toBeInTheDocument();
  });
});
