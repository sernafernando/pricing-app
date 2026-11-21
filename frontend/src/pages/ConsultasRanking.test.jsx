/**
 * Ranking de Productos values the stock at costo SI (sell-in-costo-si T3 PR 10, unit B): a stocked product with an
 * unknown cost comes with a null valuation and reads "Sin costo" (never $0 or a bare "—"), and the capital KPI card
 * and the resumen totals say how many products are not in their sums ("N productos sin costo").
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import ConsultasRanking from './ConsultasRanking';
import * as service from '../services/consultasService';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../services/consultasService', () => ({
  getRanking: vi.fn(),
  getRankingFacets: vi.fn(),
  getRankingKpis: vi.fn(),
  getRankingResumen: vi.fn(),
  getStockStatus: vi.fn(),
  refreshStock: vi.fn(),
}));

const fila = (itemId, codigo, stock, ars, usd) => ({
  item_id: itemId,
  codigo,
  descripcion: `Producto ${codigo}`,
  marca: 'MARCA DEMO',
  categoria: 'CAMARAS',
  moneda_costo: ars == null ? null : 'USD',
  pm: null,
  dias_sin_venta: 30,
  erp_ageing_dias: null,
  last_purchase_date: null,
  last_purchase_qty: null,
  total_stock: stock,
  valor_costo_ars: ars,
  valor_costo_usd: usd,
  valor_venta: null,
});

const KPIS = {
  total_productos: 3,
  stock_total: 15,
  capital_costo_ars: 200000,
  capital_costo_usd: 200,
  capital_venta_ars: null,
  capital_muerto_ars: 0,
  pct_capital_muerto: 0,
  productos_sin_costo: 1,
};

const grupo = (nombre, ars, usd, sinCosto) => ({
  grupo: nombre,
  pm: null,
  num_productos: 2,
  stock_total: 15,
  valor_costo_ars: ars,
  valor_costo_usd: usd,
  valor_venta: null,
  productos_sin_costo: sinCosto,
});

beforeEach(() => {
  vi.clearAllMocks();
  service.getRanking.mockResolvedValue({
    items: [fila(1, 'CONCOSTO', 10, 200000, 200), fila(2, 'SINCOSTO', 5, null, null), fila(3, 'SINSTOCK', 0, null, null)],
    total: 3,
    page: 1,
    page_size: 50,
  });
  service.getRankingFacets.mockResolvedValue({ marcas: [], categorias: [], pms: [], depositos: [] });
  service.getRankingKpis.mockResolvedValue(KPIS);
  service.getRankingResumen.mockResolvedValue({
    items: [grupo('MARCA DEMO', 200000, 200, 2), grupo('OTRA MARCA', null, null, 1)],
    totales: { ...grupo('TOTAL', 200000, 200, 3), num_productos: 4 },
  });
  service.getStockStatus.mockResolvedValue({ last_updated: null, syncing: false });
});

describe('ConsultasRanking — Sin costo', () => {
  it('a stocked product without a cost reads "Sin costo"; one without stock keeps "—"', async () => {
    render(<ConsultasRanking />);

    const sinCosto = (await screen.findByText('SINCOSTO')).closest('tr');
    expect(within(sinCosto).getByLabelText('Sin costo')).toHaveTextContent('Sin costo');
    expect(within(sinCosto).queryByText(/\$\s?0/)).toBeNull();

    const sinStock = screen.getByText('SINSTOCK').closest('tr');
    expect(within(sinStock).queryByLabelText('Sin costo')).toBeNull();

    const conCosto = screen.getByText('CONCOSTO').closest('tr');
    expect(within(conCosto).queryByLabelText('Sin costo')).toBeNull();
  });

  it('the capital KPI card says how many products are not in its sum', async () => {
    render(<ConsultasRanking />);

    const kpis = await screen.findByRole('region', { name: 'KPIs de capital' });
    expect(await within(kpis).findByText('1 producto sin costo')).toBeInTheDocument();
  });

  it('the resumen counts the products without cost per group and in the totals', async () => {
    render(<ConsultasRanking />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Resumen' }));

    const marca = (await screen.findByText('MARCA DEMO', { selector: 'td' })).closest('tr');
    expect(within(marca).getByText('2 productos sin costo')).toBeInTheDocument();

    const otra = screen.getByText('OTRA MARCA', { selector: 'td' }).closest('tr');
    expect(within(otra).getByLabelText('Sin costo')).toHaveTextContent('Sin costo');

    const total = screen.getByText('TOTAL').closest('tr');
    expect(within(total).getByText('3 productos sin costo')).toBeInTheDocument();
  });

  it('without products lacking a cost there is no note', async () => {
    service.getRankingKpis.mockResolvedValue({ ...KPIS, productos_sin_costo: 0 });
    render(<ConsultasRanking />);

    await screen.findByText('CONCOSTO');
    await screen.findByRole('region', { name: 'KPIs de capital' });
    expect(screen.queryByText(/sin costo$/)).toBeNull();
  });
});
