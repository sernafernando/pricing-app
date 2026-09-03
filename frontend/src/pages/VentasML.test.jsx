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
    expect(screen.getByText('Cubierta por ML')).toBeInTheDocument();
    expect(screen.queryByText('Cancelada')).not.toBeInTheDocument();
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

    expect(screen.getByText('Cancelada')).toBeInTheDocument();
    expect(screen.getByText('En depósito')).toBeInTheDocument();
    expect(screen.queryByText('Cubierta por ML')).not.toBeInTheDocument();
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

    expect(screen.getByText('Devuelto sin entregar')).toBeInTheDocument();
    expect(screen.queryByText('En depósito')).not.toBeInTheDocument();
  });

  it('keeps an unclassified sale visible on both axes as "A revisar"', async () => {
    mockSalesList([UNKNOWN_SALE]);
    await renderWithRouter(<VentasML />);
    await waitFor(() => {
      expect(screen.getByText('comprador3')).toBeInTheDocument();
    });
    const revisarBadges = screen.getAllByText('A revisar');
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

    const monthInput = screen.getByLabelText(/mes de la venta/i);
    await userEvent.type(monthInput, '2026-08');
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

    expect(await screen.findByText(/Pack 2000014816536209/)).toBeInTheDocument();
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
    expect(await screen.findByText('52.618,10 ARS')).toBeInTheDocument();
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
