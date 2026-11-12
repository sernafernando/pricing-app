import { describe, it, expect } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
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

describe('TabPedidosCompra — eje procesal retiro copy', () => {
  it('shows Por retirar when requiere_envio and eje=por_recibir', async () => {
    renderTab({
      ...PEDIDO_CON_NUMERO,
      requiere_envio: true,
      eje_procesal: 'por_recibir',
    });
    expect(await screen.findByTestId('chip-eje-procesal')).toHaveTextContent('Por retirar');
  });

  it('shows Retirando when requiere_envio and arribo_en_curso', async () => {
    renderTab({
      ...PEDIDO_CON_NUMERO,
      requiere_envio: true,
      eje_procesal: 'por_recibir',
      arribo_en_curso: true,
    });
    expect(await screen.findByTestId('chip-eje-procesal')).toHaveTextContent('Retirando');
  });

  it('shows Recibiendo when arribo_en_curso without requiere_envio', async () => {
    renderTab({
      ...PEDIDO_CON_NUMERO,
      requiere_envio: false,
      eje_procesal: 'por_recibir',
      arribo_en_curso: true,
    });
    expect(await screen.findByTestId('chip-eje-procesal')).toHaveTextContent('Recibiendo');
  });

  it('shows Retirado when requiere_envio and eje=recibido', async () => {
    renderTab({
      ...PEDIDO_CON_NUMERO,
      requiere_envio: true,
      eje_procesal: 'recibido',
    });
    expect(await screen.findByTestId('chip-eje-procesal')).toHaveTextContent('Retirado');
  });

  it('keeps Por recibir when requiere_envio is false', async () => {
    renderTab({ ...PEDIDO_CON_NUMERO, requiere_envio: false });
    expect(await screen.findByTestId('chip-eje-procesal')).toHaveTextContent('Por recibir');
  });
});

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

describe('TabPedidosCompra — chip tones and con faltantes overlap', () => {
  it('uses distinct Factura vs Match-error tones and keeps Con faltantes visible', async () => {
    renderTab({
      ...PEDIDO_CON_NUMERO,
      estado: 'con_faltantes',
      oc_vinculada: true,
      ocs: [{ oc_comp_id: 1, oc_bra_id: 1, oc_poh_id: 100 }],
      factura_cargada: true,
      oc_match_status: 'error',
    });

    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(screen.getByTestId('chip-oc')).toHaveAttribute('data-tone', 'info');
    expect(screen.getByTestId('chip-factura-cargada')).toHaveAttribute('data-tone', 'success');
    expect(screen.getByTestId('chip-match-error')).toHaveAttribute('data-tone', 'danger');
    const estado = screen.getByTestId('estado-cell');
    expect(estado).toHaveTextContent(/con faltantes/i);
    expect(estado).toHaveAttribute('data-layout', 'no-clip');
    expect(screen.getByTestId('proceso-cell')).toHaveAttribute('data-layout', 'no-clip');
  });
});

describe('TabPedidosCompra — Empresa wrap is name-agnostic', () => {
  it('shows raw names with no br and no data-wrap', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/administracion/compras/pedidos') {
        return Promise.resolve({
          data: {
            items: [
              { ...PEDIDO_CON_NUMERO, id: 1, numero: 'P-01-2026-00001', empresa_nombre: 'Empresa Uno' },
              { ...PEDIDO_CON_NUMERO, id: 2, numero: 'P-01-2026-00002', empresa_nombre: 'Otra Firma' },
            ],
            total: 2,
            page: 1,
            page_size: 50,
          },
        });
      }
      if (url === '/admin/empresas') {
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: { items: [], total: 0 } });
    });

    render(
      <MemoryRouter initialEntries={['/']}>
        <SearchProbe />
        <TabPedidosCompra />
      </MemoryRouter>
    );

    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(screen.getByText('P-01-2026-00002')).toBeInTheDocument();

    const cells = screen.getAllByTestId('empresa-cell');
    expect(cells).toHaveLength(2);
    expect(cells[0]).toHaveTextContent('Empresa Uno');
    expect(cells[1]).toHaveTextContent('Otra Firma');
    for (const cell of cells) {
      expect(cell.querySelector('br')).toBeNull();
      expect(cell).not.toHaveAttribute('data-wrap');
    }
  });
});

describe('TabPedidosCompra — Fecha pago col width', () => {
  const colWidthByHeader = (label) => {
    const headers = screen.getAllByRole('columnheader');
    const index = headers.findIndex((th) => th.textContent === label);
    expect(index).toBeGreaterThanOrEqual(0);
    const table = headers[index].closest('table');
    const cols = table.querySelectorAll('colgroup col');
    expect(cols.length).toBe(headers.length);
    return cols[index].style.width;
  };

  const fechaPagoCell = () => {
    const headers = screen.getAllByRole('columnheader');
    const index = headers.findIndex((th) => th.textContent === 'Fecha pago');
    expect(index).toBeGreaterThanOrEqual(0);
    const table = headers[index].closest('table');
    return table.querySelector('tbody tr').children[index];
  };

  const isoDaysFromToday = (delta) => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() + delta);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  };

  const formatExpected = (iso) => {
    const [y, m, d] = iso.split('-');
    return `${d}/${m}/${y}`;
  };

  it('sizes Fecha pago to 110px and leaves Estado/Proceso unchanged', async () => {
    renderTab(PEDIDO_CON_NUMERO);

    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(colWidthByHeader('Fecha pago')).toBe('110px');
    expect(colWidthByHeader('Estado')).toBe('152px');
    expect(colWidthByHeader('Proceso')).toBe('220px');
    expect(Number.parseInt(colWidthByHeader(''), 10)).toBeLessThan(180);
  });

  it.each([
    { days: 3, badge: '3d' },
    { days: 0, badge: 'Hoy' },
    { days: -2, badge: 'Vencido 2d' },
  ])(
    'renders dd/mm/yyyy + $badge for aprobado pay date and keeps col at 110px',
    async ({ days, badge }) => {
      const fecha = isoDaysFromToday(days);
      renderTab({
        ...PEDIDO_CON_NUMERO,
        estado: 'aprobado',
        fecha_pago_estimada: fecha,
      });

      expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
      const cell = fechaPagoCell();
      expect(cell).toHaveTextContent(formatExpected(fecha));
      expect(cell).toHaveTextContent(badge);
      expect(colWidthByHeader('Fecha pago')).toBe('110px');
    }
  );
});

describe('TabPedidosCompra — OC, producto/EAN and creado por filters', () => {
  const LISTADO = '/administracion/compras/pedidos';
  const CREADORES = [
    { id: 11, nombre: 'Ana Compras' },
    { id: 12, nombre: 'Beto Compras' },
  ];

  function renderWithCreadores() {
    mockPedidosApis(PEDIDO_CON_NUMERO);
    const base = api.get.getMockImplementation();
    api.get.mockImplementation((url, config) => {
      if (url === '/administracion/compras/usuarios-filtro-creado-por') {
        return Promise.resolve({ data: CREADORES });
      }
      return base(url, config);
    });
    return render(
      <MemoryRouter>
        <TabPedidosCompra />
      </MemoryRouter>
    );
  }

  const lastListParams = () => {
    const calls = api.get.mock.calls.filter(([url]) => url === LISTADO);
    return calls[calls.length - 1][1].params;
  };

  it('renders the three filters with the creator options from the endpoint', async () => {
    renderWithCreadores();

    expect(await screen.findByText('P-01-2026-00001')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Nº OC…')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Producto / EAN en OC…')).toBeInTheDocument();
    const select = screen.getByLabelText('Filtrar por usuario que creó el pedido');
    expect(await screen.findByRole('option', { name: 'Ana Compras' })).toBeInTheDocument();
    expect(select).toHaveValue('');
    expect(lastListParams()).not.toHaveProperty('q_oc');
    expect(lastListParams()).not.toHaveProperty('q_producto');
    expect(lastListParams()).not.toHaveProperty('creado_por_id');
  });

  it('sends q_numero to the backend instead of filtering the page client-side', async () => {
    const user = userEvent.setup();
    renderWithCreadores();
    await screen.findByText('P-01-2026-00001');

    await user.type(screen.getByPlaceholderText('Nº pedido…'), 'zzz');

    await waitFor(() => expect(lastListParams()).toMatchObject({ q_numero: 'zzz' }));
    // The backend answered with this pedido, so it stays listed.
    expect(screen.getByText('P-01-2026-00001')).toBeInTheDocument();
  });

  it('sends q_oc with digits only', async () => {
    const user = userEvent.setup();
    renderWithCreadores();
    await screen.findByText('P-01-2026-00001');

    await user.type(screen.getByPlaceholderText('Nº OC…'), '45/503');

    expect(screen.getByPlaceholderText('Nº OC…')).toHaveValue('45503');
    await waitFor(() => expect(lastListParams()).toMatchObject({ q_oc: '45503' }));
  });

  it('sends q_producto only from 2 characters on', async () => {
    const user = userEvent.setup();
    renderWithCreadores();
    await screen.findByText('P-01-2026-00001');
    const input = screen.getByPlaceholderText('Producto / EAN en OC…');

    await user.type(input, 'T');
    // Let the 300 ms debounce settle on the 1-character value.
    await act(() => new Promise((r) => setTimeout(r, 400)));
    expect(lastListParams()).not.toHaveProperty('q_producto');

    await user.type(input, 'A');
    await waitFor(() => expect(lastListParams()).toMatchObject({ q_producto: 'TA' }));
  });

  it('sends creado_por_id as a number for the chosen creator', async () => {
    const user = userEvent.setup();
    renderWithCreadores();
    await screen.findByRole('option', { name: 'Beto Compras' });

    await user.selectOptions(screen.getByLabelText('Filtrar por usuario que creó el pedido'), '12');

    await waitFor(() => expect(lastListParams()).toMatchObject({ creado_por_id: 12 }));
  });

  it('clearing the filters drops their params from the next request', async () => {
    const user = userEvent.setup();
    renderWithCreadores();
    await screen.findByRole('option', { name: 'Ana Compras' });
    const select = screen.getByLabelText('Filtrar por usuario que creó el pedido');

    await user.type(screen.getByPlaceholderText('Nº OC…'), '503');
    await user.type(screen.getByPlaceholderText('Producto / EAN en OC…'), 'TAPO');
    await user.selectOptions(select, '11');
    await waitFor(() =>
      expect(lastListParams()).toMatchObject({ q_oc: '503', q_producto: 'TAPO', creado_por_id: 11 })
    );

    for (const btn of screen.getAllByRole('button', { name: 'Limpiar búsqueda' })) {
      await user.click(btn);
    }
    await user.selectOptions(select, '');

    await waitFor(() => {
      const params = lastListParams();
      expect(params).not.toHaveProperty('q_oc');
      expect(params).not.toHaveProperty('q_producto');
      expect(params).not.toHaveProperty('creado_por_id');
    });
  });
});
