/**
 * Ventas ML for a `tplink.solo` user (metricas-ml-tplink-mode P7): TP figures
 * in place of every Gauss one, no call to the endpoints that answer 403 for
 * this user, and only the TP stores in the "Tienda:" chips.
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { renderWithRouter } from '../test/renderWithRouter';
import VentasML from './VentasML';
import api, { productosAPI } from '../services/api';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: ['ml_ops.ver', 'tplink.solo'],
    tienePermiso: () => true,
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const tpOrder = (over) => ({
  pack_id: null,
  status: 'paid',
  date_created: '2026-10-10T10:00:00Z',
  buyer_nickname: 'comprador',
  total_amount: 1000,
  paid_amount: 1000,
  currency_id: 'ARS',
  operation_status: 'paid',
  goods_status: 'delivered',
  neto: 800,
  metrics_state: 'ok',
  items: [{ item_id: 'MLA1', title: 'Router TP-Link Archer', quantity: 1 }],
  ...over,
});

const asGroup = (order) => ({
  group_key: `o:${order.order_id}`,
  pack_id: null,
  date_created: order.date_created,
  buyer_nickname: order.buyer_nickname,
  total_amount: order.total_amount,
  currency_id: 'ARS',
  operation_status: order.operation_status,
  goods_status: order.goods_status,
  neto: order.neto,
  total_tp: order.total_tp,
  tp_incompleto: order.tp_incompleto,
  orders: [order],
});

const KNOWN = tpOrder({ order_id: 3001, costo_tp: 500, total_tp: 811.02, markup_tp: 62.2, tp_incompleto: false });
const INCOMPLETE = tpOrder({ order_id: 3002, costo_tp: null, total_tp: null, markup_tp: null, tp_incompleto: true });

const FACETS = {
  operation_status: {},
  goods_status: {},
  operation_status_total: 2,
  goods_status_total: 2,
  alerts_total: 0,
  stores: { 2645: 1, 471846: 1 },
  stores_total: 2,
};

const KPI_TP = {
  groups_count: 2,
  orders_count: 2,
  gross_billed_ars: 2000,
  gross_billed_other: {},
  neto_sum: 1600,
  neto_unknown_count: 0,
  recalculating_count: 0,
  pending_count: 0,
  failed_count: 0,
  excluded_non_money_orders_count: 0,
  excluded_non_money_ars: 0,
  worker_alive: true,
  total_tp_sum: 811.02,
  tp_incompleto_count: 1,
  markup_tp_weighted_pct: 62.2,
};

beforeEach(() => {
  seedTiendasOficiales([
    { store_id: 57997, nombre: 'Gauss', clave: null, orden: 0, activa: true },
    { store_id: 2645, nombre: 'TP-Link vieja', clave: 'tplink', orden: 1, activa: false },
    { store_id: 471846, nombre: 'TP-Link', clave: 'tplink', orden: 2, activa: true },
  ]);
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/ml-ventas-ops/sales') {
      return Promise.resolve({
        data: { sales: [asGroup(KNOWN), asGroup(INCOMPLETE)], total: 2, limit: 50, offset: 0, facets: FACETS },
      });
    }
    if (url === '/ml-ventas-ops/sales/kpis') return Promise.resolve({ data: KPI_TP });
    if (url === '/ml-ventas-ops/divergences') return Promise.reject({ response: { status: 403 } });
    if (url === '/usuarios/pms') return Promise.resolve({ data: [] });
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

afterAll(resetTiendasOficiales);

describe('Ventas ML in TP mode', () => {
  it('shows Total TP in the table and the KPI strip, and no Gauss wording anywhere', async () => {
    await renderWithRouter(<VentasML />);
    const table = await screen.findByRole('table');
    await waitFor(() => expect(within(table).getByText('811,02', { exact: false })).toBeInTheDocument());
    expect(within(table).getByRole('columnheader', { name: /Total TP/ })).toBeInTheDocument();
    const kpis = await screen.findByRole('region', { name: 'Métricas principales' });
    await waitFor(() => expect(kpis).toHaveTextContent('Total TP'));
    expect(kpis).toHaveTextContent('TP incompleto');
    expect(document.body).not.toHaveTextContent(/gauss/i);
  });

  it('renders an unknown TP figure as a dash with "incompleto", never 0', async () => {
    await renderWithRouter(<VentasML />);
    const table = await screen.findByRole('table');
    await waitFor(() => expect(within(table).getByText('incompleto')).toBeInTheDocument());
    const row = within(table).getByText('incompleto').closest('tr');
    expect(row).toHaveTextContent('—');
  });

  it('never asks for the divergences, which answer 403 for this user', async () => {
    await renderWithRouter(<VentasML />);
    await screen.findByRole('table');
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales', expect.anything()));
    expect(api.get.mock.calls.some(([url]) => url.startsWith('/ml-ventas-ops/divergences'))).toBe(false);
    expect(screen.queryByText(/Ver divergencias/)).not.toBeInTheDocument();
  });

  it('offers only the TP stores the facet returned', async () => {
    await renderWithRouter(<VentasML />);
    const group = await screen.findByRole('group', { name: 'Filtrar por tienda oficial' });
    await waitFor(() => expect(within(group).getByRole('button', { name: /TP-Link/ })).toBeInTheDocument());
    expect(within(group).queryByRole('button', { name: /Sin tienda/ })).not.toBeInTheDocument();
    expect(within(group).getByRole('button', { name: 'Todas · 2' })).toBeInTheDocument();
  });

  it('never sends a sort the backend rejects', async () => {
    await renderWithRouter(<VentasML />);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/sales', expect.anything()));
    for (const [, config] of api.get.mock.calls) {
      expect(config?.params?.sort).not.toBe('total_gauss');
    }
  });
});
