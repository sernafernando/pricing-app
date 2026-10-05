import { describe, it, expect } from 'vitest';
import { buildMetricasMLParams } from './metricasMlParams';

const BASE = {
  fechaDesde: '2026-09-01',
  fechaHasta: '2026-09-30',
  compararCon: 'periodo_anterior',
  groupBy: 'product',
  searchQuery: '',
  productFilters: { marcas: [], subcategorias: [], pms: [] },
  storeFilter: '',
  pubStatus: [],
  pubType: [],
  alerts: [],
  soloConVentas: true,
};

describe('buildMetricasMLParams', () => {
  it('always sends the period, comparison, grouping and the "solo con ventas" toggle', () => {
    expect(buildMetricasMLParams(BASE)).toEqual({
      date_from: '2026-09-01',
      date_to: '2026-09-30',
      comparar_con: 'periodo_anterior',
      group_by: 'product',
      solo_con_ventas: true,
    });
  });

  it('sends the stock chips as include / exclude CSV, only when set', () => {
    expect(buildMetricasMLParams({ ...BASE, stock: [], stockExclude: [] })).not.toHaveProperty('stock');
    const params = buildMetricasMLParams({ ...BASE, stock: ['sin_stock', 'sin_dato'], stockExclude: ['con_stock'] });
    expect(params).toMatchObject({ stock: 'sin_stock,sin_dato', stock_exclude: 'con_stock' });
  });

  it('sends the ageing chips as include / exclude CSV, only when set', () => {
    expect(buildMetricasMLParams({ ...BASE, ageing: [], ageingExclude: [] })).not.toHaveProperty('ageing');
    const params = buildMetricasMLParams({ ...BASE, ageing: ['over_60'], ageingExclude: ['up_to_30'] });
    expect(params).toMatchObject({ ageing: 'over_60', ageing_exclude: 'up_to_30' });
  });

  it('sends the toggle explicitly when off, never relying on the backend default', () => {
    expect(buildMetricasMLParams({ ...BASE, soloConVentas: false }).solo_con_ventas).toBe(false);
  });

  it('sends every active filter as the CSV the endpoint takes', () => {
    const params = buildMetricasMLParams({
      ...BASE,
      searchQuery: 'epson',
      productFilters: { marcas: ['Epson', 'Sony'], subcategorias: [3], pms: [7] },
      storeFilter: '57997',
      pubStatus: ['active', 'paused'],
      pubType: ['full'],
      alerts: ['sin_ventas_30d'],
    });
    expect(params).toMatchObject({
      q: 'epson',
      marcas: 'Epson,Sony',
      subcategorias: '3',
      pms: '7',
      stores: '57997',
      pub_status: 'active,paused',
      pub_type: 'full',
      alerts: 'sin_ventas_30d',
    });
  });

  it('sends the excluded statuses and types as their own CSV, only when set', () => {
    expect(buildMetricasMLParams({ ...BASE, pubStatusExclude: [], pubTypeExclude: [] })).not.toHaveProperty(
      'pub_status_exclude',
    );
    const params = buildMetricasMLParams({
      ...BASE,
      pubStatusExclude: ['paused', 'closed'],
      pubTypeExclude: ['catalogo'],
    });
    expect(params).toMatchObject({ pub_status_exclude: 'paused,closed', pub_type_exclude: 'catalogo' });
    expect(params).not.toHaveProperty('pub_status');
  });
});
