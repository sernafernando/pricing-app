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
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
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

function mockSalesList(rows, { total, facets } = {}) {
  api.get.mockImplementation((url) => {
    if (url === '/ml-ventas-ops/sales') {
      return Promise.resolve({
        data: {
          sales: rows,
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
      data: { sales: rows, total: rows.length, limit: 50, offset: 0, facets: { operation_status: {}, goods_status: {} } },
    });
    resolvers[1](page([PAID_SALE]));
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    resolvers[0](page([ML_COVERED_SALE]));
    await waitFor(() => expect(screen.getByText('comprador1')).toBeInTheDocument());

    expect(screen.queryByText('comprador2')).not.toBeInTheDocument();
  });
});
