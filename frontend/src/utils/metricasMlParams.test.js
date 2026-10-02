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
};

describe('buildMetricasMLParams', () => {
  it('always sends the period, comparison and grouping', () => {
    expect(buildMetricasMLParams(BASE)).toEqual({
      date_from: '2026-09-01',
      date_to: '2026-09-30',
      comparar_con: 'periodo_anterior',
      group_by: 'product',
    });
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
