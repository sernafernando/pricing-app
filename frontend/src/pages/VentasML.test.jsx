/**
 * Tests for VentasML.jsx (ml-ventas-listado-ui).
 *
 * Scope:
 *  - `ml_ops.ver` gates visibility.
 *  - GET /ml-ventas-ops/sales called with limit/offset and active filters.
 *  - 403 vs 503 render distinct messages.
 *  - `cancelled_ml_covered` never reads as a plain cancellation.
 *  - `unknown` (either axis) stays visible.
 *  - Operation/goods status chips filter independently and reset offset.
 *  - A stale response never overwrites the list (sequence guard).
 *  - Empty list and paging past the first page.
 *  - A pack renders as ONE row whose spoiler holds its orders.
 *
 * The endpoint returns GROUPS (a pack, or a lone order). `asGroup` wraps a
 * lone-order fixture into that shape so the fixtures stay readable as the
 * orders they describe.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import VentasML from './VentasML';
import api from '../services/api';

const mockTienePermiso = vi.fn(() => true);

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (codigo) => mockTienePermiso(codigo),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const PAID_SALE = {
  order_id: 1001,
  pack_id: null,
  status: 'paid',
  date_created: '2026-08-20T10:00:00Z',
  buyer_nickname: 'comprador1',
  total_amount: 100,
  paid_amount: 100,
  currency_id: 'ARS',
  payment_status: 'approved',
  shipping_status: 'delivered',
  operation_status: 'paid',
  goods_status: 'delivered',
};

const ML_COVERED_SALE = {
  order_id: 1002,
  pack_id: null,
  status: 'cancelled',
  date_created: '2026-08-19T10:00:00Z',
  buyer_nickname: 'comprador2',
  total_amount: 50,
  paid_amount: 50,
  currency_id: 'ARS',
  payment_status: 'refunded',
  shipping_status: 'in_warehouse',
  operation_status: 'cancelled_ml_covered',
  goods_status: 'in_warehouse',
};

const UNKNOWN_SALE = {
  order_id: 1003,
  pack_id: null,
  status: null,
  date_created: '2026-08-18T10:00:00Z',
  buyer_nickname: 'comprador3',
  total_amount: 30,
  paid_amount: 0,
  currency_id: 'ARS',
  payment_status: null,
  shipping_status: null,
  operation_status: 'unknown',
  goods_status: 'unknown',
};

function asGroup(order) {
  return {
    group_key: `o:${order.order_id}`,
    pack_id: null,
    date_created: order.date_created,
    buyer_nickname: order.buyer_nickname,
    total_amount: order.total_amount,
    currency_id: order.currency_id,
    shipping_status: order.shipping_status,
    operation_status: order.operation_status,
    goods_status: order.goods_status,
    neto: order.neto,
    neto_depositado: order.neto_depositado,
    // The API's group row carries its own Total Gauss; leaving it out here
    // silently made every assertion about that cell pass for the wrong
    // reason (the value was absent, not withheld).
    total_gauss: order.total_gauss,
    total_gauss_provisional: order.total_gauss_provisional,
    retenciones_recuperables: order.retenciones_recuperables,
    modo_logistico: order.modo_logistico,
    orders: [order],
  };
}

function packOf(orders, packId) {
  return {
    group_key: `p:${packId}`,
    pack_id: packId,
    date_created: orders[0].date_created,
    buyer_nickname: orders[0].buyer_nickname,
    total_amount: orders.reduce((sum, o) => sum + o.total_amount, 0),
    // The backend sums the members' nets for the group row; without this
    // every pack rendered `—` in Neto and no test could tell the
    // difference -- a blind spot in the very column this feature adds.
    neto: orders.every((o) => o.neto != null)
      ? orders.reduce((sum, o) => sum + o.neto, 0)
      : null,
    currency_id: orders[0].currency_id,
    shipping_status: orders[0].shipping_status,
    operation_status: orders[0].operation_status,
    goods_status: orders[0].goods_status,
    orders,
  };
}

function mockSalesList(rows, { total, facets } = {}) {
  api.get.mockImplementation((url) => {
    if (url === '/ml-ventas-ops/sales') {
      return Promise.resolve({
        data: {
          sales: rows.map((row) => (row.group_key ? row : asGroup(row))),
          total: total ?? rows.length,
          limit: 50,
          offset: 0,
          facets: facets ?? { operation_status: {}, goods_status: {} },
        },
      });
    }
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  mockTienePermiso.mockReset();
  mockTienePermiso.mockImplementation(() => true);
  api.get.mockReset();
  mockSalesList([]);
  // The global jsdom `localStorage` stub (`src/test/setup.js`) persists
  // across tests in the same file -- without this, one test's saved
  // column-visibility state (ventas-ml-columnas) leaks into the next.
  localStorage.clear();
});

describe('Visibility gated by ml_ops.ver', () => {
  it('renders nothing when ml_ops.ver is not granted', async () => {
    mockTienePermiso.mockImplementation(() => false);
    const { container } = await renderWithRouter(<VentasML />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the page when ml_ops.ver is granted', async () => {
    await renderWithRouter(<VentasML />);
    expect(await screen.findByText('Ventas ML')).toBeInTheDocument();
  });
});

describe('Fetching the list', () => {
  it('calls GET /ml-ventas-ops/sales with limit=50 and offset=0 on mount', async () => {
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/ml-ventas-ops/sales',
        expect.objectContaining({ params: expect.objectContaining({ limit: 50, offset: 0 }) })
      );
    });
  });

  it('sends NO date bounds until a range is chosen', async () => {
    // The endpoint treats an absent range as "everything", so sending an
    // empty or defaulted bound would silently narrow the list on first
    // load without the operator asking for it.
    mockSalesList([]);
    await renderWithRouter(<VentasML />);

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
      expect(calls.length).toBeGreaterThan(0);
      expect(calls[0][1].params).not.toHaveProperty('date_from');
      expect(calls[0][1].params).not.toHaveProperty('date_to');
    });
  });

  it('sends the chosen range as date_from/date_to', async () => {
    // THE wiring this feature exists for. Without it the filter renders,
    // the operator clicks, and the list does not change -- which reads as
    // "the filter is broken" rather than "the request never carried it".
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(2026, 8, 17, 12, 0, 0)); // 2026-09-17, local
    try {
      mockSalesList([]);
      await renderWithRouter(<VentasML />);
      await waitFor(() => {
        expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales', expect.anything());
      });

      await userEvent.click(screen.getByRole('button', { name: '7d' }));

      await waitFor(() => {
        const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
        const ultima = calls[calls.length - 1][1].params;
        // 7d is hoy - 6, the same window métricas produces.
        expect(ultima.date_from).toBe('2026-09-11');
        expect(ultima.date_to).toBe('2026-09-17');
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it('sends no sold_month at all: the month picker is gone from this page', async () => {
    // The shared date range REPLACED the month picker here. Two controls
    // for one axis meant the endpoint silently preferred one of them, so
    // the field could read "Septiembre" over a list filtered to 7 days.
    mockSalesList([]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales', expect.anything());
    });

    expect(document.querySelector('input[type="month"]')).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: '7d' }));

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
      expect(calls[calls.length - 1][1].params).toHaveProperty('date_from');
      // EVERY call, not just the last: a `sold_month` slipping into the
      // first load would filter the list before the operator touched
      // anything, and checking only the newest request would miss it.
      for (const [, config] of calls) {
        expect(config.params).not.toHaveProperty('sold_month');
      }
    });
  });

  it('limpiar filtros drops the date range too, not just the chips', async () => {
    // The range is a filter like any other: leaving it applied while the
    // chips reset would show "sin filtros" over a list that is still
    // filtered.
    mockSalesList([]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales', expect.anything());
    });

    await userEvent.click(screen.getByRole('button', { name: '7d' }));
    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
      expect(calls[calls.length - 1][1].params).toHaveProperty('date_from');
    });

    await userEvent.click(screen.getByRole('button', { name: /limpiar/i }));

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
      const ultima = calls[calls.length - 1][1].params;
      expect(ultima).not.toHaveProperty('date_from');
      expect(ultima).not.toHaveProperty('date_to');
    });
  });

  it('shows an empty state when no sales match', async () => {
    mockSalesList([]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(screen.getByText(/no hay ventas que coincidan/i)).toBeInTheDocument();
    });
  });

  it('paginates past the first page and resets on filter change', async () => {
    mockSalesList([], { total: 200 });
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales', expect.anything());
    });

    await user.click(screen.getByRole('button', { name: /siguiente/i }));
    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
      expect(calls[calls.length - 1][1].params.offset).toBe(50);
    });

    const paidChip = screen.getByRole('button', { name: /^Pagada/ });
    await user.click(paidChip);

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
      const last = calls[calls.length - 1];
      expect(last[1].params).toEqual(
        expect.objectContaining({ offset: 0, operation_status: 'paid' })
      );
    });
  });
});

describe('403 vs 503 — distinct messages', () => {
  it('shows a permission message on 403', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/sales') {
        return Promise.reject({ response: { status: 403 } });
      }
      return Promise.resolve({ data: {} });
    });
    await renderWithRouter(<VentasML />);
    expect(await screen.findByText(/no ten[eé]s permiso/i)).toBeInTheDocument();
  });

  it('shows a feature-disabled message on 503', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/sales') {
        return Promise.reject({ response: { status: 503 } });
      }
      return Promise.resolve({ data: {} });
    });
    await renderWithRouter(<VentasML />);
    expect(await screen.findByText(/deshabilitada/i)).toBeInTheDocument();
  });
});

describe('The two axes are independent and read correctly', () => {
  it('renders a ML-covered cancellation as covered, never as a plain cancellation', async () => {
    mockSalesList([ML_COVERED_SALE]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(screen.getByText('comprador2')).toBeInTheDocument();
    });
    // Scoped to the sale's row: the filter chips carry every label too.
    const row = screen.getByText('comprador2').closest('tr');
    expect(within(row).getByText('Cubierta por ML')).toBeInTheDocument();
    expect(within(row).queryByText('Cancelada')).not.toBeInTheDocument();
  });

  it('renders a plain cancellation as cancelled, with the goods still in the warehouse', async () => {
    // The covered case asserts "Cancelada" is ABSENT. Nothing asserted it
    // appears when it should, so both could have been broken at once — and
    // this is the row whose two axes carry the most operational weight: the
    // money did not come in, and the product never left.
    const CANCELLED_SALE = {
      ...PAID_SALE,
      order_id: 1005,
      status: 'cancelled',
      buyer_nickname: 'comprador5',
      operation_status: 'cancelled',
      goods_status: 'in_warehouse',
      shipping_status: 'ready_to_ship',
    };
    mockSalesList([CANCELLED_SALE]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(screen.getByText('comprador5')).toBeInTheDocument();
    });

    const row = screen.getByText('comprador5').closest('tr');
    expect(within(row).getByText('Cancelada')).toBeInTheDocument();
    expect(within(row).getByText('En depósito')).toBeInTheDocument();
    expect(within(row).queryByText('Cubierta por ML')).not.toBeInTheDocument();
  });

  it('tells a returned sale apart from one that never shipped', async () => {
    // Both leave the goods with the seller, and they are not the same
    // situation: one came back, the other never left.
    const RETURNED_SALE = {
      ...PAID_SALE,
      order_id: 1006,
      status: 'cancelled',
      buyer_nickname: 'comprador6',
      operation_status: 'cancelled',
      goods_status: 'returned_undelivered',
      shipping_status: 'not_delivered',
    };
    mockSalesList([RETURNED_SALE]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(screen.getByText('comprador6')).toBeInTheDocument();
    });

    const row = screen.getByText('comprador6').closest('tr');
    expect(within(row).getByText('Devuelto sin entregar')).toBeInTheDocument();
    expect(within(row).queryByText('En depósito')).not.toBeInTheDocument();
  });

  it('keeps an unclassified sale visible on both axes as "A revisar"', async () => {
    mockSalesList([UNKNOWN_SALE]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(screen.getByText('comprador3')).toBeInTheDocument();
    });
    // Scoped to the table: the "Incluir" toggle carries the same name.
    const revisarBadges = within(screen.getByRole('table')).getAllByText('A revisar');
    expect(revisarBadges.length).toBe(2);
  });

  it('filters operation status and goods status as independent chip groups', async () => {
    mockSalesList([PAID_SALE], {
      facets: { operation_status: { paid: 1 }, goods_status: { delivered: 1 } },
    });
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    const operationGroup = screen.getByRole('group', { name: /filtrar por estado de operación/i });
    const goodsGroup = screen.getByRole('group', { name: /filtrar por estado de la mercadería/i });
    expect(operationGroup).toBeInTheDocument();
    expect(goodsGroup).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^En depósito/ }));
    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
      const last = calls[calls.length - 1];
      expect(last[1].params).toEqual(
        expect.objectContaining({ goods_status: 'in_warehouse', offset: 0 })
      );
      expect(last[1].params.operation_status).toBeUndefined();
    });
  });

  it('clicking an active chip clears it', async () => {
    mockSalesList([PAID_SALE], { facets: { operation_status: { paid: 1 }, goods_status: {} } });
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    const paidChip = screen.getByRole('button', { name: /^Pagada/ });
    await user.click(paidChip);
    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
      expect(calls[calls.length - 1][1].params.operation_status).toBe('paid');
    });

    await user.click(paidChip);
    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
      expect(calls[calls.length - 1][1].params.operation_status).toBeUndefined();
    });
  });
});

// ventas-ml-rediseno PR14.T1-T4 (SEARCH R25, R26, R27).
describe('Search box (ventas-ml-rediseno PR14)', () => {
  it('sends the debounced query as `q`, combined with the active status filter', async () => {
    mockSalesList([PAID_SALE], { facets: { operation_status: { paid: 1 }, goods_status: {} } });
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /^Pagada/ }));
    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
      expect(calls[calls.length - 1][1].params.operation_status).toBe('paid');
    });

    await user.type(screen.getByRole('searchbox'), 'comprador1');

    await waitFor(
      () => {
        const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
        const last = calls[calls.length - 1];
        // SEARCH R26: intersection, not replacement — the status filter set
        // moments ago is still on the request that carries the search term.
        expect(last[1].params).toEqual(
          expect.objectContaining({ q: 'comprador1', operation_status: 'paid', offset: 0 })
        );
      },
      { timeout: 2000 }
    );
  });

  it('resets offset to 0 when the query changes', async () => {
    mockSalesList(
      Array.from({ length: 3 }, (_, i) => ({ ...PAID_SALE, order_id: 1000 + i })),
      { total: 3, facets: { operation_status: { paid: 3 }, goods_status: {} } }
    );
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getAllByText('comprador1').length).toBeGreaterThan(0));

    await user.type(screen.getByRole('searchbox'), 'x');
    await waitFor(
      () => {
        const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
        expect(calls[calls.length - 1][1].params.offset).toBe(0);
      },
      { timeout: 2000 }
    );
  });

  it('shows an explicit "sin resultados" message when the search term matches nothing (SEARCH R27)', async () => {
    mockSalesList([PAID_SALE], { facets: { operation_status: { paid: 1 }, goods_status: {} } });
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    // Next fetch (triggered by the search term) resolves to an empty set.
    mockSalesList([], { facets: { operation_status: {}, goods_status: {} } });
    await user.type(screen.getByRole('searchbox'), 'nadie-existe');

    await waitFor(() => expect(screen.getByText(/sin resultados/i)).toBeInTheDocument(), {
      timeout: 2000,
    });
    // The list's own empty state ("no hay ventas...") coexists — this
    // assertion only pins the search-specific message exists, never an
    // error styling (see SalesToolbar.test.jsx for the style assertion).
  });
});

describe('a stale response never overwrites the list', () => {
  it('ignores an older request that resolves last', async () => {
    const resolvers = [];
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/sales') {
        return new Promise((resolve) => resolvers.push(resolve));
      }
      return Promise.resolve({ data: {} });
    });

    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(resolvers.length).toBe(1));

    // Any filter change triggers the second request; the month picker
    // this used to type into was removed when the shared date range
    // replaced it. The subject here is the sequence guard, not which
    // control fired it.
    await userEvent.click(screen.getByRole('button', { name: '7d' }));
    await waitFor(() => expect(resolvers.length).toBe(2));

    const page = (rows) => ({
      data: {
        sales: rows.map((row) => (row.group_key ? row : asGroup(row))),
        total: rows.length,
        limit: 50,
        offset: 0,
        facets: { operation_status: {}, goods_status: {} },
      },
    });
    resolvers[1](page([PAID_SALE]));
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    resolvers[0](page([ML_COVERED_SALE]));
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    expect(screen.queryByText('comprador2')).not.toBeInTheDocument();
  });
});

// `vitest.config.js` runs with `css: false` (no layout, no computed
// styles) so this cannot assert stickiness or that a column actually
// fits a compressed width -- only that the header row exists as a
// structural sibling of `<tbody>` (not nested inside a scrolling wrapper
// around it) and that every column survives, which is what CSS Modules
// compression must not remove. Sticky behaviour and the FHD/wide-monitor
// visual are verified by hand (see the PR description).
describe('Table header structure (ventas-ml-encabezados-fijos-y-tabla-compacta)', () => {
  it('renders the header row as a direct sibling of the body, not inside a nested scroll wrapper', async () => {
    mockSalesList([asGroup(PAID_SALE)]);
    await renderWithRouter(<VentasML />);

    await screen.findByText(PAID_SALE.buyer_nickname);
    const table = screen.getByRole('table');
    // `<colgroup>` (ventas-ml-columnas T2, column-geometry sizing) is a
    // legitimate direct table child ahead of `<thead>` — the concern this
    // test guards is that `<thead>`/`<tbody>` are direct children of
    // `<table>` and not nested inside some scrolling wrapper, not their
    // exact sibling index.
    expect(Array.from(table.children)).toContain(table.querySelector('thead'));
    expect(Array.from(table.children)).toContain(table.querySelector('tbody'));
  });

  it('keeps every column header even with the panel open (compression, not hiding)', async () => {
    mockSalesList([asGroup(PAID_SALE)]);
    await renderWithRouter(<VentasML />, {
      initialEntries: [`/ventas-ml?orden=${PAID_SALE.order_id}`],
    });

    await screen.findByText(PAID_SALE.buyer_nickname);
    const headerRow = screen.getAllByRole('columnheader');
    const headerTexts = headerRow.map((th) => th.textContent);
    expect(headerTexts).toEqual(
      expect.arrayContaining([
        'Producto',
        'Orden',
        'Comprador',
        // One column, two pills: the money axis above the goods axis.
        'Estado',
        'Envío',
        'Importe',
        'Neto',
        'Total Gauss',
      ]),
    );
  });
});

describe('Configurable columns (ventas-ml-columnas)', () => {
  const CP_A1 = {
    ...PAID_SALE,
    order_id: 3000018230951686,
    pack_id: 3000014816536209,
    total_amount: 100,
    buyer_nickname: 'CPBUYER',
  };
  const CP_A2 = {
    ...PAID_SALE,
    order_id: 3000018230945962,
    pack_id: 3000014816536209,
    total_amount: 200,
    buyer_nickname: 'CPBUYER',
  };

  function packOfCp() {
    return {
      group_key: 'p:3000014816536209',
      pack_id: 3000014816536209,
      date_created: CP_A1.date_created,
      buyer_nickname: 'CPBUYER',
      total_amount: CP_A1.total_amount + CP_A2.total_amount,
      neto: null,
      currency_id: 'ARS',
      shipping_status: CP_A1.shipping_status,
      operation_status: CP_A1.operation_status,
      goods_status: CP_A1.goods_status,
      orders: [CP_A1, CP_A2],
    };
  }

  // T4 — THE ONE THING THAT MUST NOT BREAK: hiding a column via the picker
  // must remove it from the header, the group row, AND every expanded
  // pack-member row, in the same order. If a member row keeps rendering a
  // column the group row hid, every cell after that point shifts and money
  // ends up under the wrong header for that row.
  it('hides a column from the group row and its expanded pack-member rows together', async () => {
    const user = userEvent.setup();
    mockSalesList([packOfCp()]);
    await renderWithRouter(<VentasML />);

    const toggle = await screen.findByRole('button', { name: /Pack 3000014816536209/ });
    await user.click(toggle);
    const groupRow = toggle.closest('tr');
    const memberRows = (await screen.findAllByText(/^300001823/)).map((el) => el.closest('tr'));

    const cellCountBefore = within(groupRow).getAllByRole('cell').length;
    memberRows.forEach((row) => {
      expect(within(row).getAllByRole('cell').length).toBe(cellCountBefore);
    });

    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    await user.click(screen.getByRole('checkbox', { name: 'Envío' }));

    await waitFor(() => {
      expect(within(groupRow).getAllByRole('cell').length).toBe(cellCountBefore - 1);
    });
    const cellCountAfter = within(groupRow).getAllByRole('cell').length;
    memberRows.forEach((row) => {
      expect(within(row).getAllByRole('cell').length).toBe(cellCountAfter);
    });
    // And the header itself agrees.
    expect(screen.queryAllByRole('columnheader').map((h) => h.textContent)).not.toContain('Envío');
  });

  // T5 — the empty/loading state's colSpan must track the VISIBLE column
  // count, not a hardcoded constant that goes stale the moment a column is
  // hidden (it used to be `TABLE_COLUMN_COUNT = 11`).
  it('keeps the empty-state colSpan in sync with the visible column count', async () => {
    const user = userEvent.setup();
    mockSalesList([]);
    await renderWithRouter(<VentasML />);

    await screen.findByText('No hay ventas que coincidan con los filtros');
    const headerCountBefore = screen.getAllByRole('columnheader').length;
    let emptyCell = screen.getByText('No hay ventas que coincidan con los filtros');
    expect(Number(emptyCell.getAttribute('colspan'))).toBe(headerCountBefore);

    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    await user.click(screen.getByRole('checkbox', { name: 'Envío' }));

    await waitFor(() => {
      const headerCountAfter = screen.getAllByRole('columnheader').length;
      expect(headerCountAfter).toBe(headerCountBefore - 1);
    });
    emptyCell = screen.getByText('No hay ventas que coincidan con los filtros');
    expect(Number(emptyCell.getAttribute('colspan'))).toBe(headerCountBefore - 1);
  });

  // T6 — a column may be unhideable for two different reasons, and both
  // have to hold. Producto and Total Gauss carry the whole point of the
  // screen; Orden and Neto carry the only CONTROLS.
  it('never offers Producto or Total Gauss in the column picker', async () => {
    const user = userEvent.setup();
    mockSalesList([asGroup(PAID_SALE)]);
    await renderWithRouter(<VentasML />);
    await screen.findByText(PAID_SALE.buyer_nickname);

    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    expect(screen.queryByRole('checkbox', { name: 'Producto' })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Total Gauss' })).not.toBeInTheDocument();
  });

  // Reviewer-found: hiding a column that holds a CONTROL does not hide data,
  // it removes functionality — and the choice is persisted in localStorage,
  // so the operator is stuck with it across reloads, with nothing on screen
  // explaining why packs stopped opening.
  //
  //   - `orden` holds `packToggle` (`aria-expanded`), the ONLY way to expand a
  //     pack and see the orders inside it. Hidden, the pack's members are
  //     unreachable by mouse AND by keyboard.
  //   - `neto` holds the `aria-label="Ver desglose de costos"` button, which
  //     the column file itself documents as the keyboard route to the detail
  //     panel (the row click is a mouse-only shortcut). Hidden, the panel has
  //     no keyboard route at all.
  it('never offers Orden or Neto either, because they hold the only controls', async () => {
    const user = userEvent.setup();
    mockSalesList([asGroup(PAID_SALE)]);
    await renderWithRouter(<VentasML />);
    await screen.findByText(PAID_SALE.buyer_nickname);

    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    expect(screen.queryByRole('checkbox', { name: 'Orden' })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Neto' })).not.toBeInTheDocument();
  });

  // T7 — corrupted/disabled localStorage must never take the screen down
  // with it; the fail-safe discipline from `tiendaNubeReconcileTableHelpers.js`
  // (filter-to-known-ids, try/catch) applies here too.
  it('survives a corrupted column-visibility payload in localStorage', async () => {
    // The jsdom `localStorage` stub (`src/test/setup.js`) is a plain
    // object with its own `getItem`, not a real `Storage` instance --
    // spying on `Storage.prototype` would never reach it. Writing directly
    // through the stub's own `setItem` is what actually reproduces a
    // corrupted payload for `loadColumnVisibility`'s `JSON.parse` to trip
    // over.
    localStorage.setItem('ventasml:colvisibility', '{not json');
    mockSalesList([asGroup(PAID_SALE)]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText(PAID_SALE.buyer_nickname)).toBeInTheDocument();
    expect(screen.getAllByRole('columnheader').length).toBeGreaterThan(0);
  });
});

describe('A pack is one row', () => {
  // The production report (2026-09-02): three rows, same buyer, same
  // timestamp, where two were a single parcel and the third another.
  const PACK_A1 = {
    ...PAID_SALE,
    order_id: 2000018230951686,
    pack_id: 2000014816536209,
    total_amount: 27868.1,
    buyer_nickname: 'ELIAADRIANAREYES',
  };
  const PACK_A2 = {
    ...PAID_SALE,
    order_id: 2000018230945962,
    pack_id: 2000014816536209,
    total_amount: 24750,
    buyer_nickname: 'ELIAADRIANAREYES',
  };

  it('shows the pack, not its orders, until it is opened', async () => {
    mockSalesList([packOf([PACK_A1, PACK_A2], 2000014816536209)]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByRole('button', { name: /Pack 2000014816536209/ })).toBeInTheDocument();
    expect(screen.getByText('2 órdenes')).toBeInTheDocument();
    expect(screen.queryByText('2000018230951686')).not.toBeInTheDocument();
  });

  it('reveals the orders inside when opened, and hides them again', async () => {
    mockSalesList([packOf([PACK_A1, PACK_A2], 2000014816536209)]);
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);

    const toggle = await screen.findByRole('button', { name: /Pack 2000014816536209/ });
    await user.click(toggle);

    expect(await screen.findByText('2000018230951686')).toBeInTheDocument();
    expect(screen.getByText('2000018230945962')).toBeInTheDocument();

    await user.click(toggle);
    await waitFor(() => {
      expect(screen.queryByText('2000018230951686')).not.toBeInTheDocument();
    });
  });

  it('shows the amount of the whole parcel, not of one of its orders', async () => {
    mockSalesList([packOf([PACK_A1, PACK_A2], 2000014816536209)]);
    await renderWithRouter(<VentasML />);

    // 27.868,10 + 24.750,00 — the number that was invisible while the
    // three rows stood apart.
    expect(await screen.findByText('$ 52.618,10')).toBeInTheDocument();
  });

  it('gives a lone order no spoiler to open', async () => {
    mockSalesList([PAID_SALE]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('1001')).toBeInTheDocument();
    expect(screen.queryByText(/órdenes$/)).not.toBeInTheDocument();
  });

  it('renders a pack whose orders disagree as mixed, never picking a winner', async () => {
    const mixed = packOf([PACK_A1, PACK_A2], 2000014816536209);
    mixed.operation_status = 'mixed';
    mockSalesList([mixed]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('Mixta')).toBeInTheDocument();
    // Scoped to the table: "Pagada" also appears as a filter chip, and
    // asserting against the whole document would pass for the wrong reason.
    const table = screen.getByRole('table');
    expect(within(table).queryByText('Pagada')).not.toBeInTheDocument();
  });

  it('does not offer "Mixta" as a filter — it is a property of a row, not of an order', async () => {
    await renderWithRouter(<VentasML />);
    await screen.findByText('Ventas ML');
    expect(screen.queryByRole('button', { name: /^Mixta/ })).not.toBeInTheDocument();
  });

  it('survives a group that carries no orders instead of white-screening', async () => {
    const broken = packOf([PACK_A1], 1);
    delete broken.orders;
    mockSalesList([broken]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('ELIAADRIANAREYES')).toBeInTheDocument();
  });

  it("shows the pack's own net on its row, and each member's on theirs", async () => {
    // The only Neto path covered was the lone-order one. A pack row takes
    // a different branch, and until `packOf` carried `neto` at all every
    // pack rendered a dash that nothing could contradict.
    const user = userEvent.setup();
    mockSalesList([
      packOf(
        [
          { ...PACK_A1, neto: 60 },
          { ...PACK_A2, neto: 40 },
        ],
        2000014816536209,
      ),
    ]);

    await renderWithRouter(<VentasML />);

    const toggle = await screen.findByRole('button', { name: /Pack 2000014816536209/ });
    // The group row carries the sum of its members.
    expect(await screen.findByRole('button', { name: 'Ver desglose de costos' })).toHaveTextContent(
      '100,00',
    );

    await user.click(toggle);
    const netoButtons = await screen.findAllByRole('button', { name: 'Ver desglose de costos' });
    const textos = netoButtons.map((b) => b.textContent);
    expect(textos.some((t) => t.includes('60,00'))).toBe(true);
    expect(textos.some((t) => t.includes('40,00'))).toBe(true);
  });

  it('opening a pack does NOT also open the breakdown drawer', async () => {
    // The toggle lives inside a row whose own onClick opens the drawer,
    // so it calls stopPropagation. Nothing covered that: delete the call
    // and every other test stays green while the operator gets a panel
    // they never asked for on top of the orders they wanted to see.
    const pack = packOf([PACK_A1, PACK_A2], 2000014816536209);
    const user = userEvent.setup();
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/sales') {
        return Promise.resolve({
          data: {
            sales: [pack],
            total: 1,
            limit: 50,
            offset: 0,
            facets: { operation_status: {}, goods_status: {} },
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    await renderWithRouter(<VentasML />);

    const toggle = await screen.findByRole('button', { name: /Pack 2000014816536209/ });
    await user.click(toggle);

    // The orders are revealed...
    expect(await screen.findByText('2000018230951686')).toBeInTheDocument();
    // ...and no breakdown was ever requested.
    expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining('/ml-ventas-ops/orders/'));
    expect(screen.queryByLabelText('Detalle de venta')).not.toBeInTheDocument();
  });

  describe('PR19 — selecting a pack row opens the PACK panel, not an arbitrary member', () => {
    // The product filters (`ventas-ml-filtros-producto`) and the pack panel
    // (PR19) were built on separate branches off the same main and only met
    // at the merge. Nothing covered them TOGETHER, and a merge is exactly
    // where two independently-correct features stop cooperating: both write
    // to the same URL search params and both read from `useVentasMLFilters`.
    it('opens the pack panel even with a product filter active', async () => {
      const grupo = packOf([PACK_A1, PACK_A2], 2000014816536209);
      api.get.mockImplementation((url) => {
        if (url === '/ml-ventas-ops/sales') {
          return Promise.resolve({
            data: {
              sales: [grupo],
              total: 1,
              limit: 50,
              offset: 0,
              facets: { operation_status: {}, goods_status: {} },
            },
          });
        }
        if (url === '/ml-ventas-ops/packs/2000014816536209') {
          return Promise.resolve({
            data: {
              pack_id: 2000014816536209,
              monto_operacion: 52618.1,
              item_lines: [],
              item_lines_reconcilia: true,
              item_lines_razon: null,
              total_gauss: 40000,
              costo_mercaderia: 20000,
              markup: 100,
              member_order_ids: [2000018230951686, 2000018230945962],
            },
          });
        }
        return Promise.resolve({ data: {} });
      });
      const user = userEvent.setup();
      await renderWithRouter(<VentasML />, { initialEntries: ['/?marcas=Sony'] });

      // Precondition, asserted and not assumed: the filter really IS active
      // and travelling. Without this the test would pass on a build where
      // the filter silently stopped working.
      await waitFor(() => {
        expect(api.get).toHaveBeenCalledWith(
          '/ml-ventas-ops/sales',
          expect.objectContaining({ params: expect.objectContaining({ marcas: 'Sony' }) }),
        );
      });

      await screen.findByRole('button', { name: /Pack 2000014816536209/ });
      await user.click(screen.getByText(PACK_A1.buyer_nickname));

      expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/packs/2000014816536209');
      // And the filter survived the selection: picking a pack must not wipe
      // the filter out of the URL.
      const ultimaVenta = api.get.mock.calls
        .filter(([url]) => url === '/ml-ventas-ops/sales')
        .at(-1);
      expect(ultimaVenta[1].params.marcas).toBe('Sony');
    });

    it('calls GET /ml-ventas-ops/packs/{pack_id}, never opening the order-scoped panel of a member (PANEL R22)', async () => {
      mockSalesList([packOf([PACK_A1, PACK_A2], 2000014816536209)]);
      api.get.mockImplementation((url) => {
        if (url === '/ml-ventas-ops/sales') {
          return Promise.resolve({
            data: {
              sales: [packOf([PACK_A1, PACK_A2], 2000014816536209)],
              total: 1,
              limit: 50,
              offset: 0,
              facets: { operation_status: {}, goods_status: {} },
            },
          });
        }
        if (url === '/ml-ventas-ops/packs/2000014816536209') {
          return Promise.resolve({
            data: {
              pack_id: 2000014816536209,
              monto_operacion: 52618.1,
              item_lines: [],
              item_lines_reconcilia: true,
              item_lines_razon: null,
              total_gauss: 40000,
              costo_mercaderia: 20000,
              markup: 100,
              member_order_ids: [2000018230951686, 2000018230945962],
            },
          });
        }
        return Promise.resolve({ data: {} });
      });
      const user = userEvent.setup();
      await renderWithRouter(<VentasML />);

      // Clicking the pack LABEL itself lands inside the expand toggle
      // <button>, which calls stopPropagation -- the buyer cell is a plain
      // <td>, so a click there bubbles to the row's own onClick, same as
      // an operator clicking anywhere on the row that is not the toggle.
      await screen.findByRole('button', { name: /Pack 2000014816536209/ });
      const buyerCell = screen.getByText(PACK_A1.buyer_nickname);
      await user.click(buyerCell);

      // The bug this PR fixes: the CURRENT handler called
      // openDrawer(orders[0].order_id), which would have requested
      // GET /ml-ventas-ops/orders/2000018230951686 instead.
      expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/packs/2000014816536209');
      expect(api.get).not.toHaveBeenCalledWith(
        expect.stringContaining('/ml-ventas-ops/orders/2000018230951686'),
      );
      expect(await screen.findByText('Desglose del pack 2000014816536209')).toBeInTheDocument();
    });

    it('navigates from the pack panel to a member order\'s own order-scoped panel (PANEL R23 scenario 10)', async () => {
      api.get.mockImplementation((url) => {
        if (url === '/ml-ventas-ops/sales') {
          return Promise.resolve({
            data: {
              sales: [packOf([PACK_A1, PACK_A2], 2000014816536209)],
              total: 1,
              limit: 50,
              offset: 0,
              facets: { operation_status: {}, goods_status: {} },
            },
          });
        }
        if (url === '/ml-ventas-ops/packs/2000014816536209') {
          return Promise.resolve({
            data: {
              pack_id: 2000014816536209,
              monto_operacion: 52618.1,
              item_lines: [],
              item_lines_reconcilia: true,
              item_lines_razon: null,
              total_gauss: 40000,
              costo_mercaderia: 20000,
              markup: 100,
              member_order_ids: [2000018230951686, 2000018230945962],
            },
          });
        }
        if (url === `/ml-ventas-ops/orders/${PACK_A1.order_id}`) {
          return Promise.resolve({
            data: {
              breakdown: {
                lines: [],
                neto: 27868.1,
                incompleto: false,
                incomplete_reasons: [],
              },
            },
          });
        }
        return Promise.resolve({ data: {} });
      });
      const user = userEvent.setup();
      await renderWithRouter(<VentasML />);

      const buyerCell = await screen.findByText(PACK_A1.buyer_nickname);
      await user.click(buyerCell);
      await screen.findByText('Desglose del pack 2000014816536209');

      const memberButton = await screen.findByRole('button', { name: String(PACK_A1.order_id) });
      await user.click(memberButton);

      // The pack panel is gone; the order-scoped panel for JUST that
      // member is open (its own monto_operacion/lines, not the pack's).
      expect(await screen.findByText('Desglose de costos')).toBeInTheDocument();
      expect(screen.queryByText('Desglose del pack 2000014816536209')).not.toBeInTheDocument();
      expect(api.get).toHaveBeenCalledWith(`/ml-ventas-ops/orders/${PACK_A1.order_id}`);
    });
  });
});

describe('The "Todas" chip follows the same arithmetic as the chips beside it', () => {
  it('counts the axis facets, not the doubly-filtered total', async () => {
    // `total` is scoped by BOTH axes; the facets by the OTHER one. Reading
    // `total` here made "Todas" smaller than the sum of the chips under it
    // as soon as the other axis was filtered.
    // A mixed pack counts in two buckets, so the buckets sum to 11 while
    // only 10 rows exist. Neither `total` (1, scoped by both axes) nor the
    // bucket sum (11) is the number the chip must show.
    mockSalesList([PAID_SALE], {
      total: 1,
      facets: {
        operation_status: { paid: 8, cancelled: 3 },
        goods_status: { in_warehouse: 10 },
        operation_status_total: 10,
        goods_status_total: 10,
      },
    });
    await renderWithRouter(<VentasML />);

    const operationGroup = await screen.findByRole('group', {
      name: /estado de operaci[oó]n/i,
    });
    expect(within(operationGroup).getByRole('button', { name: 'Todas · 10' })).toBeInTheDocument();
    expect(within(operationGroup).queryByRole('button', { name: 'Todas · 11' })).not.toBeInTheDocument();
    expect(within(operationGroup).queryByRole('button', { name: 'Todas · 1' })).not.toBeInTheDocument();
  });
});

describe('The Neto column', () => {
  it('shows a dash when neto is null — payments have not synced yet, not zero', async () => {
    mockSalesList([{ ...PAID_SALE, neto: null }]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    const row = screen.getByText('comprador1').closest('tr');
    // Scoped to the Neto button specifically: with `total_gauss` also
    // unset on this fixture, the Total Gauss cell renders its OWN dash
    // now too, so a bare `getByText('—')` would find two and fail.
    expect(within(row).getByRole('button', { name: 'Ver desglose de costos' })).toHaveTextContent('—');
  });

  it('shows a real zero when neto is 0 — a fully returned sale, never a dash', async () => {
    mockSalesList([{ ...PAID_SALE, neto: 0 }]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    const row = screen.getByText('comprador1').closest('tr');
    expect(within(row).getByText('$ 0,00')).toBeInTheDocument();
  });

  it('formats a positive neto like the other money columns', async () => {
    mockSalesList([{ ...PAID_SALE, neto: 82.5 }]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    const row = screen.getByText('comprador1').closest('tr');
    expect(within(row).getByText('$ 82,50')).toBeInTheDocument();
  });

  // The listing is denominated in ARS, so the suffix is dropped there to
  // leave the amount its column width. A foreign currency is NOT implied
  // and must stay spelled out, or a USD sale reads as a pesos sale.
  it('keeps the currency suffix on a sale that is not in ARS', async () => {
    mockSalesList([{ ...PAID_SALE, neto: 82.5, currency_id: 'USD' }]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    const row = screen.getByText('comprador1').closest('tr');
    expect(within(row).getByText('82,50 USD')).toBeInTheDocument();
    expect(within(row).queryByText('82,50')).not.toBeInTheDocument();
  });

  // Dropping the visible suffix must not drop the information: the cell
  // still carries the unabridged value, currency included.
  it('keeps the full amount with its currency in the cell tooltip', async () => {
    mockSalesList([{ ...PAID_SALE, total_amount: 1234567.89 }]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    const cell = screen.getByText('$ 1.234.567,89').closest('td');
    expect(cell).toHaveAttribute('title', '1.234.567,89 ARS');
  });

  // SM R3/R9: while metrics are recalculating the stale figure is hidden
  // behind the badge. A `title` is another way of reading it, so it has to
  // obey the same rule -- otherwise hovering reveals exactly what the badge
  // is there to withhold.
  it('does not leak the stale Total Gauss through the tooltip while recalculating', async () => {
    mockSalesList([{ ...PAID_SALE, total_gauss: 70, metrics_state: 'recalculating' }]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    const row = screen.getByText('comprador1').closest('tr');
    const leaked = Array.from(row.querySelectorAll('[title]')).map((el) => el.title);
    expect(leaked.some((t) => t.includes('70,00'))).toBe(false);
  });

  it('shows the "MP $X · SIRTAC $Y" tooltip when retenciones_recuperables > 0', async () => {
    mockSalesList([
      { ...PAID_SALE, neto: 503958.14, neto_depositado: 502165.91, retenciones_recuperables: 1792.23 },
    ]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    const row = screen.getByText('comprador1').closest('tr');
    const netoButton = within(row).getByRole('button', { name: 'Ver desglose de costos' });
    expect(netoButton).toHaveAttribute('title', 'MP $ 502.165,91 · SIRTAC $ 1.792,23');
  });

  it.each([
    ['0', 0],
    // null is what the backend emits for rows without relevant payments
    // and for mixed-currency packs.
    ['null', null],
  ])('carries no tooltip when retenciones_recuperables is %s', async (_label, retenciones) => {
    mockSalesList([{ ...PAID_SALE, neto: 500, neto_depositado: 500, retenciones_recuperables: retenciones }]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    const row = screen.getByText('comprador1').closest('tr');
    const netoButton = within(row).getByRole('button', { name: 'Ver desglose de costos' });
    expect(netoButton).not.toHaveAttribute('title');
  });
});

describe('Opening the cost breakdown panel (ventas-ml-rediseno PR13, non-modal)', () => {
  it('opens the panel when a lone-order row is clicked, fetching its breakdown', async () => {
    mockSalesList([{ ...PAID_SALE, neto: 100 }]);
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/sales') {
        return Promise.resolve({
          data: {
            sales: [asGroup({ ...PAID_SALE, neto: 100 })],
            total: 1,
            limit: 50,
            offset: 0,
            facets: { operation_status: {}, goods_status: {} },
          },
        });
      }
      if (url === '/ml-ventas-ops/orders/1001') {
        return Promise.resolve({
          data: {
            breakdown: {
              lines: [{ concepto: 'Cargo por vender', monto: 12.5, origen: 'api' }],
              neto: 87.5,
              incompleto: false,
              incomplete_reasons: [],
            },
          },
        });
      }
      return Promise.resolve({ data: {} });
    });
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    await user.click(screen.getByText('comprador1').closest('tr'));

    expect(await screen.findByLabelText('Detalle de venta')).toBeInTheDocument();
    expect(await screen.findByText('Cargo por vender')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/orders/1001');
  });

  it('lets the row that opened the panel stay independently selectable/copyable (PANEL R17)', async () => {
    mockSalesList([{ ...PAID_SALE, neto: 100 }]);
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/sales') {
        return Promise.resolve({
          data: {
            sales: [asGroup({ ...PAID_SALE, neto: 100 })],
            total: 1,
            limit: 50,
            offset: 0,
            facets: { operation_status: {}, goods_status: {} },
          },
        });
      }
      if (url === '/ml-ventas-ops/orders/1001') {
        return Promise.resolve({
          data: {
            breakdown: {
              lines: [{ concepto: 'Cargo por vender', monto: 12.5, origen: 'api' }],
              neto: 87.5,
              incompleto: false,
              incomplete_reasons: [],
            },
          },
        });
      }
      return Promise.resolve({ data: {} });
    });
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    await user.click(screen.getByText('comprador1').closest('tr'));
    await screen.findByLabelText('Detalle de venta');

    // The whole reason this PR exists is that a row must stay
    // clickable/selectable while the panel is open — proven here by the
    // row staying fully reachable in the accessibility tree, focusable,
    // and structurally outside the panel, not by grepping for one known
    // testid an overlay implementation happens to use.
    const netoButton = screen.getByRole('button', { name: 'Ver desglose de costos' });
    netoButton.focus();
    expect(netoButton).toHaveFocus();

    const aside = screen.getByLabelText('Detalle de venta');
    expect(aside.contains(netoButton)).toBe(false);
    expect(netoButton.closest('aside')).toBeNull();

    // The buyer's own text, inside the table row, must stay selectable —
    // still present and un-hidden while the panel is open.
    const buyerCell = screen.getByText('comprador1');
    expect(buyerCell.closest('[aria-hidden="true"]')).toBeNull();
    expect(document.querySelector('[inert]')).toBeNull();
  });
});

describe('Ingestion-failure banner (open `ingest_failed` divergences)', () => {
  function mockDivergencesTotal(total) {
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/sales') {
        return Promise.resolve({
          data: { sales: [], total: 0, limit: 50, offset: 0, facets: { operation_status: {}, goods_status: {} } },
        });
      }
      if (url === '/ml-ventas-ops/divergences') {
        return Promise.resolve({ data: { divergences: [], total } });
      }
      return Promise.resolve({ data: {} });
    });
  }

  it('shows nothing when there are no open ingest_failed divergences', async () => {
    mockDivergencesTotal(0);
    await renderWithRouter(<VentasML />);
    await screen.findByText('Ventas ML');
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/ml-ventas-ops/divergences',
        expect.objectContaining({ params: { kind: 'ingest_failed', state: 'open', limit: 1 } })
      );
    });
    expect(screen.queryByText(/no pud(ieron|o) ingresar/i)).not.toBeInTheDocument();
  });

  it('shows a warning with a link to the divergences board when there are open failures', async () => {
    mockDivergencesTotal(3);
    await renderWithRouter(<VentasML />);

    const banner = await screen.findByText(/3 ventas no pudieron ingresar/i);
    expect(banner).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /ver divergencias/i });
    expect(link).toHaveAttribute('href', '/ml-ventas-divergencias');
  });

  it('uses singular phrasing for exactly one failure', async () => {
    mockDivergencesTotal(1);
    await renderWithRouter(<VentasML />);
    expect(await screen.findByText(/1 venta no pudo ingresar/i)).toBeInTheDocument();
  });

  it('a failure fetching divergences never breaks the sales list', async () => {
    // WHERE THE TEETH ARE, written down because it is not obvious: the two
    // assertions below pass even with the component's `.catch` removed --
    // the rejection happens outside render, so React never notices, the
    // list still draws and the banner is still absent. What actually
    // catches that regression is the RUNNER: an unhandled rejection makes
    // `vitest run` exit non-zero (verified: exit 1 with the catch removed,
    // 0 with it). So CI fails even though this file reports "passed".
    //
    // A listener asserting on `unhandledrejection` was tried and does not
    // fire under jsdom here, so it was removed rather than left in looking
    // like protection it does not provide.
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/sales') {
        return Promise.resolve({
          data: {
            sales: [asGroup(PAID_SALE)],
            total: 1,
            limit: 50,
            offset: 0,
            facets: { operation_status: {}, goods_status: {} },
          },
        });
      }
      if (url === '/ml-ventas-ops/divergences') {
        return Promise.reject(new Error('network down'));
      }
      return Promise.resolve({ data: {} });
    });

    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('comprador1')).toBeInTheDocument();
    expect(screen.queryByText(/no pud(ieron|o) ingresar/i)).not.toBeInTheDocument();
  });
});

describe("ML's raw shipping status is not rendered", () => {
  // `goods_status` is derived from `shipping_status`, so rendering both
  // said the same thing twice — once in Spanish the operator reads, once
  // in ML's untranslated English. Which status maps where is not this
  // test's business.
  it('shows the Mercadería badge instead of the raw ML value', async () => {
    mockSalesList([{ ...PAID_SALE, shipping_status: 'ready_to_ship', goods_status: 'in_warehouse' }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('En depósito')).toBeInTheDocument();
    expect(screen.queryByText('ready_to_ship')).not.toBeInTheDocument();
  });
});

describe('Modo logístico badge (ml-ventas-modo-logistico PR6)', () => {
  // Defensive first: a row missing `modo_logistico` (a shape the backend
  // must not send, but the UI must not white-screen on) renders "undefined"
  // via the raw-value fallback rather than crashing the whole listing.
  it('does not crash when modo_logistico is absent, and the row still renders', async () => {
    const { modo_logistico: _modoLogistico, ...withoutModo } = PAID_SALE;
    mockSalesList([withoutModo]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('comprador1')).toBeInTheDocument();
  });

  it('shows Flex for self_service', async () => {
    mockSalesList([{ ...PAID_SALE, modo_logistico: 'self_service' }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('Flex')).toBeInTheDocument();
  });

  it('shows Full for fulfillment', async () => {
    mockSalesList([{ ...PAID_SALE, modo_logistico: 'fulfillment' }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('Full')).toBeInTheDocument();
  });

  it('shows Colecta for cross_docking', async () => {
    mockSalesList([{ ...PAID_SALE, modo_logistico: 'cross_docking' }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('Colecta')).toBeInTheDocument();
  });

  it('shows Retiro for retiro', async () => {
    mockSalesList([{ ...PAID_SALE, modo_logistico: 'retiro' }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('Retiro')).toBeInTheDocument();
  });

  it('renders an unrecognised value verbatim, never folded into "Desconocido"', async () => {
    // The backend passes a future ML logistic type through on purpose —
    // this pins that the UI never swallows it into the known-unknown label.
    mockSalesList([{ ...PAID_SALE, modo_logistico: 'some_future_type' }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('some_future_type')).toBeInTheDocument();
    expect(screen.queryByText('Desconocido')).not.toBeInTheDocument();
  });

  it('renders an unrecognised value verbatim on the ORDER row too, not only the pack row', async () => {
    // The sibling test above uses a SINGLE sale, which renders as a pack
    // row -- so it only ever exercised the group badge. The per-order badge
    // is a second call site with its own fallback, and mutating it to fold
    // an unknown type into "Desconocido" changed nothing: a future ML
    // logistic type would have been swallowed there in silence.
    const user = userEvent.setup();
    const packA1 = { ...PAID_SALE, order_id: 3101, pack_id: 9101, modo_logistico: 'another_future_type' };
    const packA2 = { ...PAID_SALE, order_id: 3102, pack_id: 9101, modo_logistico: 'cross_docking' };
    mockSalesList([{ ...packOf([packA1, packA2], 9101), modo_logistico: 'mixed' }]);
    await renderWithRouter(<VentasML />);

    await user.click(await screen.findByRole('button', { name: /Pack 9101/ }));

    expect(await screen.findByText('another_future_type')).toBeInTheDocument();
  });

  it('shows Mixto on the pack row when its orders carry the "mixed" value', async () => {
    const packA1 = { ...PAID_SALE, order_id: 3001, pack_id: 9001, modo_logistico: 'self_service' };
    const packA2 = { ...PAID_SALE, order_id: 3002, pack_id: 9001, modo_logistico: 'cross_docking' };
    mockSalesList([
      { ...packOf([packA1, packA2], 9001), modo_logistico: 'mixed' },
    ]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('Mixto')).toBeInTheDocument();
  });
});

describe('PR14.T5 — category icon and alert icon on each row', () => {
  it('renders the category icon (by title) for a lone order carrying item_category', async () => {
    mockSalesList([{ ...PAID_SALE, item_category: 'NOTEBOOK' }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByTitle('NOTEBOOK')).toBeInTheDocument();
  });

  it('renders no category icon for a pack whose orders disagree on item_category', async () => {
    const user = userEvent.setup();
    const a1 = { ...PAID_SALE, order_id: 3201, pack_id: 9201, item_category: 'NOTEBOOK' };
    const a2 = { ...PAID_SALE, order_id: 3202, pack_id: 9201, item_category: 'ACCESORIOS' };
    mockSalesList([packOf([a1, a2], 9201)]);
    await renderWithRouter(<VentasML />);

    // The pack row itself carries no single category — never picks one
    // member's icon arbitrarily.
    expect(screen.queryByTitle('NOTEBOOK')).not.toBeInTheDocument();

    await user.click(await screen.findByRole('button', { name: /Pack 9201/ }));
    // Each member row DOES show its own category once expanded.
    expect(await screen.findByTitle('NOTEBOOK')).toBeInTheDocument();
    expect(screen.getByTitle('ACCESORIOS')).toBeInTheDocument();
  });

  it('renders no category icon at all when item_category is null (no fabricated fallback icon shown as data)', async () => {
    mockSalesList([{ ...PAID_SALE, item_category: null }]);
    await renderWithRouter(<VentasML />);

    const row = (await screen.findByText('comprador1')).closest('tr');
    // No title-based category icon anywhere in that row.
    expect(row.querySelector('svg[title]')).toBeNull();
  });

  it('renders an alert icon for alert_level="error", none for "ok"', async () => {
    mockSalesList([{ ...PAID_SALE, alert_level: 'error' }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByRole('img', { name: 'Alerta' })).toBeInTheDocument();
  });

  it('renders no alert icon for alert_level="ok"', async () => {
    mockSalesList([{ ...PAID_SALE, alert_level: 'ok' }]);
    await renderWithRouter(<VentasML />);

    await screen.findByText('Ventas ML');
    expect(screen.queryByRole('img', { name: 'Alerta' })).not.toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Advertencia' })).not.toBeInTheDocument();
  });
});

// PR14 review fix P3: `title` on an `<svg>` renders no browser tooltip — it
// needs a real (non-svg) hoverable host, and `reason` was never actually
// passed to AlertIcon from this page. Category name and alert reason must
// be genuinely discoverable on hover.
describe('PR14 review fix P3 — category and alert tooltips are on a real host element, not the svg attribute', () => {
  it('puts the category tooltip on a wrapping element, not the svg attribute', async () => {
    mockSalesList([{ ...PAID_SALE, item_category: 'NOTEBOOK' }]);
    await renderWithRouter(<VentasML />);

    const titled = await screen.findByTitle('NOTEBOOK');
    expect(titled.tagName.toLowerCase()).not.toBe('svg');
  });

  it('passes a real alert reason through to AlertIcon, derived from the order that actually failed metrics', async () => {
    mockSalesList([{ ...PAID_SALE, alert_level: 'error', metrics_state: 'failed', neto: 82.5 }]);
    await renderWithRouter(<VentasML />);

    const icon = await screen.findByRole('img', { name: 'Alerta' });
    const titled = icon.closest('[title]');
    expect(titled).not.toBeNull();
    expect(titled.getAttribute('title')).toBeTruthy();
    expect(titled.tagName.toLowerCase()).not.toBe('svg');
  });
});

describe('PR14.T9/T10 — recalculating badge never shows a stale number', () => {
  it('shows "Recalculando…" instead of the amount when metrics_state="recalculating"', async () => {
    mockSalesList([{ ...PAID_SALE, neto: 82.5, total_gauss: 70, metrics_state: 'recalculating' }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findAllByText(/Recalculando/)).toHaveLength(2); // Neto + Total Gauss cells
    expect(screen.queryByText(/82,50/)).not.toBeInTheDocument();
  });

  it('shows a distinct "no se pudo calcular" for metrics_state="failed" — never "Recalculando"', async () => {
    mockSalesList([{ ...PAID_SALE, neto: 82.5, total_gauss: 70, metrics_state: 'failed' }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findAllByText(/No se pudo calcular/)).toHaveLength(2);
    expect(screen.queryByText(/Recalculando/)).not.toBeInTheDocument();
  });

  it('shows the real number when metrics_state="ok"', async () => {
    mockSalesList([{ ...PAID_SALE, neto: 82.5, total_gauss: 70, currency_id: 'ARS', metrics_state: 'ok' }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findByText('$ 82,50')).toBeInTheDocument();
  });

  it('a pack with one recalculating member shows the badge on the pack row, not a stale sum', async () => {
    const a1 = {
      ...PAID_SALE,
      order_id: 3301,
      pack_id: 9301,
      neto: 50,
      total_gauss: 40,
      metrics_state: 'ok',
    };
    const a2 = {
      ...PAID_SALE,
      order_id: 3302,
      pack_id: 9301,
      neto: 30,
      total_gauss: 20,
      metrics_state: 'recalculating',
    };
    mockSalesList([{ ...packOf([a1, a2], 9301), neto: null, total_gauss: null }]);
    await renderWithRouter(<VentasML />);

    expect(await screen.findAllByText(/Recalculando/)).toHaveLength(2);
  });
});

// PR14 post-review fix P1: `city`/`province`/`shipping_substatus` and
// `markup` were only ever rendered inside the pack-member block, which
// never renders for a lone sale (`isPack = orders.length > 1` is false).
// Since MOST sales are lone sales, this data was invisible on most rows.
// The group row must render the same subline/markup, sourced from
// `orders[0]`, when the group is NOT a pack.
describe('PR14 review fix P1 — lone-sale subline and markup are visible', () => {
  it('shows the city/province/substatus subline on a lone sale, not only inside an opened pack', async () => {
    mockSalesList([
      { ...PAID_SALE, city: 'Rosario', province: 'Santa Fe', shipping_substatus: 'in_hub' },
    ]);
    await renderWithRouter(<VentasML />);

    const row = (await screen.findByText('comprador1')).closest('tr');
    // The city is the buyer's second line (the full place in its tooltip);
    // the substatus is the Envío cell's, translated -- never raw `in_hub`.
    expect(within(row).getByTitle('Rosario, Santa Fe')).toHaveTextContent('Rosario');
    expect(within(row).getByText('En centro de distribución')).toBeInTheDocument();
    expect(within(row).queryByText(/in_hub/)).not.toBeInTheDocument();
  });

  it('shows the markup percentage on a lone sale, not only inside an opened pack', async () => {
    mockSalesList([{ ...PAID_SALE, neto: 82.5, total_gauss: 70, metrics_state: 'ok', markup: 12.3 }]);
    await renderWithRouter(<VentasML />);

    const row = (await screen.findByText('comprador1')).closest('tr');
    expect(within(row).getByText('12,3%', { exact: false })).toBeInTheDocument();
  });

  it('renders no subline at all when city, province and substatus are all null — no fabricated dashes', async () => {
    mockSalesList([{ ...PAID_SALE, city: null, province: null, shipping_substatus: null }]);
    await renderWithRouter(<VentasML />);

    const row = (await screen.findByText('comprador1')).closest('tr');
    expect(row.textContent).not.toMatch(/·/);
  });
});

// PR14 post-review fix P2: the Neto cell's own comment says the button IS
// the keyboard affordance for the detail panel, but the button was REPLACED
// by RecalculatingBadge whenever metrics_state !== 'ok' — the exact rows
// (recalculating, failed, pending) an operator most needs to reach by
// keyboard. The button must survive, carrying the badge as its content.
describe('PR14 review fix P2 — the Neto button survives a non-ok metrics_state', () => {
  it('keeps the Neto button (with the badge inside) on the group row when metrics_state="failed"', async () => {
    mockSalesList([{ ...PAID_SALE, metrics_state: 'failed' }]);
    await renderWithRouter(<VentasML />);

    const row = (await screen.findByText('comprador1')).closest('tr');
    const netoButton = within(row).getByRole('button', { name: 'Ver desglose de costos' });
    expect(within(netoButton).getByText(/No se pudo calcular/)).toBeInTheDocument();
  });

  it('keeps the Neto button (with the badge inside) on a pack member row when metrics_state="recalculating"', async () => {
    const user = userEvent.setup();
    const a1 = { ...PAID_SALE, order_id: 4401, pack_id: 9401, metrics_state: 'ok' };
    const a2 = { ...PAID_SALE, order_id: 4402, pack_id: 9401, metrics_state: 'recalculating' };
    mockSalesList([{ ...packOf([a1, a2], 9401), neto: null }]);
    await renderWithRouter(<VentasML />);

    await user.click(await screen.findByRole('button', { name: /Pack 9401/ }));
    const memberRow = (await screen.findByText('4402')).closest('tr');
    const netoButton = within(memberRow).getByRole('button', { name: 'Ver desglose de costos' });
    expect(within(netoButton).getByText(/Recalculando/)).toBeInTheDocument();
  });
});

// ventas-ml-producto-listado-pr10b (PR14.T5/T6 blocker, finally unblocked):
// `SaleListItem.items` / `OrderItemOpsSummary` now reach the FE. The
// product cell replaces the old icon-only `Categoría` column.
describe('ProductCell — product identity on the listing (PR14b)', () => {
  // LONE-SALE case: most rows in the real table are a single order with a
  // single item. This is the discriminating case a vacuous test could miss.
  it('shows the product title, SKU, MLA and quantity for a lone sale', async () => {
    mockSalesList([
      {
        ...PAID_SALE,
        items: [
          { item_id: 'MLA2060835678', seller_sku: 'EPS-L3250', title: 'Impresora Epson EcoTank L3250', quantity: 1 },
        ],
      },
    ]);
    await renderWithRouter(<VentasML />);

    const row = (await screen.findByText('comprador1')).closest('tr');
    expect(within(row).getByText('Impresora Epson EcoTank L3250')).toBeInTheDocument();
    expect(within(row).getByText(/SKU EPS-L3250/)).toBeInTheDocument();
    expect(within(row).getByText(/MLA2060835678/)).toBeInTheDocument();
  });

  // MULTI-ITEM pack case: aggregates items across ALL orders in the pack,
  // never picks one silently. Discriminates from the lone-sale case above.
  it('shows the first item plus an explicit "+N productos" badge for a multi-item pack, aggregated across its orders', async () => {
    const a1 = {
      ...PAID_SALE,
      order_id: 5501,
      pack_id: 9501,
      items: [{ item_id: 'MLA1429582101', seller_sku: 'LEN-82YU000PAR', title: 'Lenovo V15 G4', quantity: 1 }],
    };
    const a2 = {
      ...PAID_SALE,
      order_id: 5502,
      pack_id: 9501,
      items: [{ item_id: 'MLA1198421099', seller_sku: 'SAM-LS24C310', title: 'Monitor Samsung 24"', quantity: 1 }],
    };
    mockSalesList([packOf([a1, a2], 9501)]);
    await renderWithRouter(<VentasML />);

    const packRow = (await screen.findByRole('button', { name: /Pack 9501/ })).closest('tr');
    expect(within(packRow).getByText('Lenovo V15 G4')).toBeInTheDocument();
    expect(within(packRow).getByText('+1 producto')).toBeInTheDocument();
  });

  it('shows each order own product cell once the pack is expanded', async () => {
    const user = userEvent.setup();
    const a1 = {
      ...PAID_SALE,
      order_id: 5601,
      pack_id: 9601,
      items: [{ item_id: 'MLA1429582101', seller_sku: 'LEN-82YU000PAR', title: 'Lenovo V15 G4', quantity: 1 }],
    };
    const a2 = {
      ...PAID_SALE,
      order_id: 5602,
      pack_id: 9601,
      items: [{ item_id: 'MLA1198421099', seller_sku: 'SAM-LS24C310', title: 'Monitor Samsung 24"', quantity: 1 }],
    };
    mockSalesList([packOf([a1, a2], 9601)]);
    await renderWithRouter(<VentasML />);

    await user.click(await screen.findByRole('button', { name: /Pack 9601/ }));
    const member1 = (await screen.findByText('5601')).closest('tr');
    const member2 = (await screen.findByText('5602')).closest('tr');
    expect(within(member1).getByText('Lenovo V15 G4')).toBeInTheDocument();
    expect(within(member2).getByText('Monitor Samsung 24"')).toBeInTheDocument();
  });
});

// ventas-ml-kpi-strip: the KPI strip must call the SAME filter params as
// the list (T5) — a filter that reaches one endpoint but not the other
// breaks "lo que veo es lo que suma", which is the entire point of the
// feature.
describe('the KPI strip stays in parity with the list', () => {
  function mockKpi(overrides = {}) {
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/sales') {
        return Promise.resolve({
          data: { sales: [], total: 0, limit: 50, offset: 0, facets: { operation_status: {}, goods_status: {} } },
        });
      }
      if (url === '/ml-ventas-ops/sales/kpis') {
        return Promise.resolve({
          data: {
            groups_count: 0,
            orders_count: 0,
            gross_billed_ars: 0,
            gross_billed_other: {},
            neto_sum: 0,
            neto_unknown_count: 0,
            total_gauss_sum: 0,
            total_gauss_ok_count: 0,
            total_gauss_provisional_count: 0,
            total_gauss_unresolved_count: 0,
            markup_weighted_pct: null,
            recalculating_count: 0,
            pending_count: 0,
            failed_count: 0,
            markup_skipped_count: 0,
            worker_alive: true,
            excluded_by_toggle: { a_revisar: 0, en_disputa: 0, mixta: 0, provisorio: 0 },
            effective_switches: {
              include_unknown: true,
              include_in_dispute: true,
              include_mixed: true,
              include_provisional: true,
            },
            ...overrides,
          },
        });
      }
      return Promise.resolve({ data: {} });
    });
  }

  it('calls GET /ml-ventas-ops/sales/kpis on load, with no limit/offset', async () => {
    mockKpi();
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales/kpis', expect.anything());
    });
    const kpiCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales/kpis');
    expect(kpiCall[1].params).not.toHaveProperty('limit');
    expect(kpiCall[1].params).not.toHaveProperty('offset');
  });

  it('carries a brand filter through to the KPI endpoint, not just to the list', async () => {
    // The headline promise of this screen: filter a brand, see THAT BRAND's
    // total. The parity test above only ever clicks a status facet, so a
    // regression that dropped `marcas` from the KPI request alone would sail
    // straight through it while the six cards quietly showed the total for
    // everything.
    mockKpi();
    await renderWithRouter(<VentasML />, { initialEntries: ['/?marcas=Sony'] });

    await waitFor(() => {
      const kpiCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales/kpis');
      expect(kpiCall).toBeTruthy();
      expect(kpiCall[1].params.marcas).toBe('Sony');
    });

    const listCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales');
    const kpiCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales/kpis');
    expect(kpiCall[1].params.marcas).toBe(listCall[1].params.marcas);
  });

  it('sends the exact same filter params to the list and to the KPI endpoint', async () => {
    mockKpi();
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales/kpis', expect.anything());
    });

    api.get.mock.calls.length = 0; // clear the initial-load calls, keep the mock implementation

    await user.click(screen.getAllByRole('button', { name: /^Pagada/ })[0]);

    await waitFor(() => {
      const listCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales');
      const kpiCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales/kpis');
      expect(listCall).toBeTruthy();
      expect(kpiCall).toBeTruthy();
      const { limit: _limit, offset: _offset, ...listFilterParams } = listCall[1].params;
      expect(kpiCall[1].params).toEqual(listFilterParams);
    });
  });

  it('turning a toggle off reaches both the list and the KPI request with the same value', async () => {
    mockKpi();
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales/kpis', expect.anything());
    });

    api.get.mock.calls.length = 0;

    await user.click(screen.getByRole('checkbox', { name: /a revisar/i }));

    await waitFor(() => {
      const listCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales');
      const kpiCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales/kpis');
      expect(listCall[1].params.include_unknown).toBe(false);
      expect(kpiCall[1].params.include_unknown).toBe(false);
    });
  });

  it('Canceladas off reaches the list and the KPI request, and Limpiar filtros turns it back on', async () => {
    mockKpi();
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales/kpis', expect.anything());
    });
    // Default ON: today's numbers do not change silently.
    const firstList = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales');
    expect(firstList[1].params.include_cancelled).toBe(true);

    api.get.mock.calls.length = 0;
    await user.click(screen.getByRole('checkbox', { name: /canceladas/i }));
    await waitFor(() => {
      const listCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales');
      const kpiCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales/kpis');
      expect(listCall[1].params.include_cancelled).toBe(false);
      expect(kpiCall[1].params.include_cancelled).toBe(false);
    });

    await user.click(await screen.findByRole('button', { name: /limpiar filtros/i }));
    expect(screen.getByRole('checkbox', { name: /canceladas/i })).toBeChecked();
  });

  it('Solo con alertas reaches list and KPI requests, resets the page and shows the facet count', async () => {
    mockKpi();
    const baseImpl = api.get.getMockImplementation();
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-ventas-ops/sales') {
        return Promise.resolve({
          data: {
            sales: [],
            total: 0,
            limit: 50,
            offset: 0,
            facets: { operation_status: {}, goods_status: {}, alerts_total: 7 },
          },
        });
      }
      return baseImpl(url, config);
    });
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    const chip = await screen.findByRole('button', { name: /solo con alertas/i });
    expect(chip).toHaveTextContent('Solo con alertas · 7');
    const firstList = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales');
    expect(firstList[1].params.only_alerts).toBe(false);

    api.get.mock.calls.length = 0;
    await user.click(chip);
    await waitFor(() => {
      const listCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales');
      const kpiCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales/kpis');
      expect(listCall[1].params).toMatchObject({ only_alerts: true, offset: 0 });
      expect(kpiCall[1].params.only_alerts).toBe(true);
    });

    await user.click(await screen.findByRole('button', { name: /limpiar filtros/i }));
    expect(screen.getByRole('button', { name: /solo con alertas/i })).toHaveAttribute('aria-pressed', 'false');
  });

  it('Exportar CSV sends the SAME filters as the list (no paging) and tells the operator when it fails', async () => {
    mockKpi();
    const baseImpl = api.get.getMockImplementation();
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-ventas-ops/sales/export') {
        return Promise.reject({
          response: {
            status: 422,
            data: new Blob([JSON.stringify({ error: { message: 'Son 20000 ventas. Acotá los filtros.' } })]),
          },
        });
      }
      return baseImpl(url, config);
    });
    const user = userEvent.setup();
    await renderWithRouter(<VentasML />);
    await user.click(await screen.findByRole('checkbox', { name: /canceladas/i }));
    await user.click(await screen.findByRole('button', { name: /solo con alertas/i }));
    await waitFor(() => {
      const last = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales').at(-1);
      expect(last[1].params).toMatchObject({ include_cancelled: false, only_alerts: true });
    });
    const listParams = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales').at(-1)[1].params;

    await user.click(screen.getByRole('button', { name: /exportar csv/i }));

    await waitFor(() => {
      const exportCall = api.get.mock.calls.find((c) => c[0] === '/ml-ventas-ops/sales/export');
      expect(exportCall[1].responseType).toBe('blob');
      const { limit, offset, ...listFilters } = listParams; // eslint-disable-line no-unused-vars
      expect(exportCall[1].params).toEqual(listFilters);
    });
    expect(await screen.findByText(/Acotá los filtros/)).toBeInTheDocument();
  });

  it('the panel offers Resincronizar only to who holds ml_ops.resincronizar', async () => {
    mockSalesList([asGroup(PAID_SALE)]);
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'ml_ops.resincronizar');
    const first = await renderWithRouter(<VentasML />, {
      initialEntries: [`/ventas-ml?orden=${PAID_SALE.order_id}`],
    });
    await screen.findByText('Desglose de costos');
    expect(screen.queryByRole('button', { name: /resincronizar/i })).not.toBeInTheDocument();
    first.unmount();

    mockTienePermiso.mockImplementation(() => true);
    await renderWithRouter(<VentasML />, {
      initialEntries: [`/ventas-ml?orden=${PAID_SALE.order_id}`],
    });
    expect(await screen.findByRole('button', { name: /resincronizar/i })).toBeInTheDocument();
  });

  it('shows when the sales list was last synced from ML, and nothing when it never was', async () => {
    mockKpi();
    const baseImpl = api.get.getMockImplementation();
    const when = new Date(Date.now() - 5 * 60_000).toISOString();
    api.get.mockImplementation((url, config) =>
      url === '/ml-ventas-ops/sales/sync-status'
        ? Promise.resolve({ data: { last_synced_at: when } })
        : baseImpl(url, config),
    );
    await renderWithRouter(<VentasML />);
    expect(await screen.findByText('sincronizado hace 5 min')).toBeInTheDocument();
  });

  it('does not claim a sync time when the backend has none', async () => {
    mockKpi();
    const baseImpl = api.get.getMockImplementation();
    api.get.mockImplementation((url, config) =>
      url === '/ml-ventas-ops/sales/sync-status'
        ? Promise.resolve({ data: { last_synced_at: null } })
        : baseImpl(url, config),
    );
    await renderWithRouter(<VentasML />);
    await screen.findByText('Ventas ML');
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales/sync-status'));
    expect(screen.queryByText(/sincronizado hace/i)).not.toBeInTheDocument();
  });

  it('renders a null markup_weighted_pct from the live response as "—", not 0%', async () => {
    mockKpi({ markup_weighted_pct: null });
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales/kpis', expect.anything());
    });
    await waitFor(() => {
      expect(screen.getByText('—', { selector: 'div' })).toBeInTheDocument();
    });
  });
});
