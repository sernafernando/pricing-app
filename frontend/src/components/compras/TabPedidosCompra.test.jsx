import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useSearchParams } from 'react-router-dom';
import api from '../../services/api';
import TabPedidosCompra from './TabPedidosCompra';
import AdministracionCompras from '../../pages/AdministracionCompras';
import { stripPedidoQueryParams } from '../../hooks/useRecepcionDeposito';

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

function SearchProbe() {
  const [searchParams] = useSearchParams();
  return (
    <div data-testid="search-probe">
      {searchParams.toString()}
    </div>
  );
}

function mockPedidosApis(pedido) {
  api.get.mockImplementation((url) => {
    if (url === '/administracion/compras/pedidos') {
      return Promise.resolve({
        data: { items: [pedido], total: 1, page: 1, page_size: 50 },
      });
    }
    if (url === `/administracion/compras/pedidos/${pedido.id}`) {
      return Promise.resolve({
        data: {
          ...pedido,
          factura_documentos: [],
          imputaciones: [],
          eventos: [],
        },
      });
    }
    if (url === '/admin/empresas') {
      return Promise.resolve({ data: [] });
    }
    return Promise.resolve({ data: { items: [], total: 0 } });
  });
}

function renderTab(pedido, { initialEntries = ['/'] } = {}) {
  mockPedidosApis(pedido);
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <SearchProbe />
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
});

describe('TabPedidosCompra — default filter and logistic estados', () => {
  it('sends excluir_estado=cancelado on the default empty select', async () => {
    renderTab(PEDIDO_CON_NUMERO);

    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith(
      '/administracion/compras/pedidos',
      expect.objectContaining({
        params: expect.objectContaining({ excluir_estado: 'cancelado' }),
      })
    );
    expect(screen.getByLabelText('Filtrar por estado')).toHaveValue('');
    const options = [...screen.getByLabelText('Filtrar por estado').querySelectorAll('option')].map(
      (opt) => opt.value
    );
    expect(options).toEqual(expect.arrayContaining(['recibido', 'con_faltantes', 'controlado', 'cancelado']));
  });
});

describe('TabPedidosCompra — pedido query consume-or-clear', () => {
  it('opens inbound ?pedido= once then consumes the query', async () => {
    renderTab(PEDIDO_CON_NUMERO, { initialEntries: ['/?tab=pedidos&pedido=1'] });

    expect(await screen.findByText('Pedido P-01-2026-00001')).toBeInTheDocument();
    await waitFor(() => {
      const qs = screen.getByTestId('search-probe').textContent;
      expect(qs).not.toMatch(/pedido=/);
      expect(qs).not.toMatch(/focus=/);
      expect(qs).not.toMatch(/open=/);
    });
  });

  it('Ver force-opens with an open nonce then consumes', async () => {
    const user = userEvent.setup();
    renderTab(PEDIDO_CON_NUMERO);

    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Ver detalle' }));
    expect(await screen.findByText('Pedido P-01-2026-00001')).toBeInTheDocument();
    await waitFor(() => {
      const qs = screen.getByTestId('search-probe').textContent;
      expect(qs).not.toMatch(/pedido=/);
      expect(qs).not.toMatch(/open=/);
    });
  });

  it('close clears leftover query so remount does not reopen', async () => {
    const user = userEvent.setup();
    const { unmount } = renderTab(PEDIDO_CON_NUMERO, {
      initialEntries: ['/?pedido=1&focus=observaciones'],
    });

    expect(await screen.findByText('Pedido P-01-2026-00001')).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'Cerrar' })[0]);
    await waitFor(() => {
      expect(screen.queryByText('Pedido P-01-2026-00001')).not.toBeInTheDocument();
    });
    const leftover = screen.getByTestId('search-probe').textContent;
    unmount();
    mockPedidosApis(PEDIDO_CON_NUMERO);
    render(
      <MemoryRouter initialEntries={[`/?${leftover}`]}>
        <SearchProbe />
        <TabPedidosCompra />
      </MemoryRouter>
    );
    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(screen.queryByText('Pedido P-01-2026-00001')).not.toBeInTheDocument();
  });

  it('user Compras tab click strips pedido so returning to Pedidos does not reopen', async () => {
    const user = userEvent.setup();
    mockPedidosApis(PEDIDO_CON_NUMERO);
    render(
      <MemoryRouter initialEntries={['/?tab=pedidos&pedido=1']}>
        <SearchProbe />
        <AdministracionCompras />
      </MemoryRouter>
    );

    expect(await screen.findByText('Pedido P-01-2026-00001')).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: /Depósito/ }));
    await waitFor(() => {
      expect(screen.getByTestId('search-probe').textContent).not.toMatch(/pedido=/);
    });
    await user.click(screen.getByRole('tab', { name: /Pedidos/ }));
    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(screen.queryByText('Pedido P-01-2026-00001')).not.toBeInTheDocument();
  });

  it('stripPedidoQueryParams keeps tab/eje and drops pedido/focus/open', () => {
    const next = stripPedidoQueryParams(
      new URLSearchParams('tab=pedidos&eje=recibido&pedido=12&focus=observaciones&open=abc&op_id=9')
    );
    expect(next.get('tab')).toBe('pedidos');
    expect(next.get('eje')).toBe('recibido');
    expect(next.get('op_id')).toBe('9');
    expect(next.has('pedido')).toBe(false);
    expect(next.has('focus')).toBe(false);
    expect(next.has('open')).toBe(false);
  });
});

describe('TabPedidosCompra — OC chip is vinculación', () => {
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
