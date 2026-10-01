import { describe, it, expect } from 'vitest';
import { buildVentasMLFilterParams } from './ventasMlParams';

const BASE_FILTERS = {
  operationStatusFilter: '',
  goodsStatusFilter: '',
  fechaDesde: '',
  fechaHasta: '',
  searchQuery: '',
  productFilters: { marcas: [], subcategorias: [], pms: [] },
  includeUnknown: true,
  includeInDispute: true,
  includeMixed: true,
  includeProvisional: true,
  includeCancelled: true,
  onlyAlerts: false,
};

describe('buildVentasMLFilterParams', () => {
  it('omits empty/unset filters and never sends limit or offset', () => {
    const params = buildVentasMLFilterParams(BASE_FILTERS);
    expect(params).not.toHaveProperty('operation_status');
    expect(params).not.toHaveProperty('goods_status');
    expect(params).not.toHaveProperty('date_from');
    expect(params).not.toHaveProperty('date_to');
    expect(params).not.toHaveProperty('q');
    expect(params).not.toHaveProperty('marcas');
    expect(params).not.toHaveProperty('limit');
    expect(params).not.toHaveProperty('offset');
  });

  it('includes every active filter under the exact param names the backend expects', () => {
    const params = buildVentasMLFilterParams({
      ...BASE_FILTERS,
      operationStatusFilter: 'paid',
      goodsStatusFilter: 'delivered',
      fechaDesde: '2026-09-01',
      fechaHasta: '2026-09-30',
      searchQuery: 'epson',
      productFilters: { marcas: ['acme', 'globex'], subcategorias: [1, 2], pms: [7] },
    });
    expect(params).toMatchObject({
      operation_status: 'paid',
      goods_status: 'delivered',
      date_from: '2026-09-01',
      date_to: '2026-09-30',
      q: 'epson',
      marcas: 'acme,globex',
      subcategorias: '1,2',
      pms: '7',
    });
  });

  it('always sends the four toggles explicitly, even when true', () => {
    const params = buildVentasMLFilterParams(BASE_FILTERS);
    expect(params).toMatchObject({
      include_unknown: true,
      include_in_dispute: true,
      include_mixed: true,
      include_provisional: true,
      include_cancelled: true,
    });
  });

  it('sends include_cancelled=false when Canceladas is switched off', () => {
    const params = buildVentasMLFilterParams({ ...BASE_FILTERS, includeCancelled: false });
    expect(params.include_cancelled).toBe(false);
    expect(params.include_unknown).toBe(true);
  });

  it('a caller that does not know the switch keeps cancelled sales (default ON)', () => {
    const { includeCancelled, ...withoutIt } = BASE_FILTERS; // eslint-disable-line no-unused-vars
    expect(buildVentasMLFilterParams(withoutIt).include_cancelled).toBe(true);
  });

  it('sends only_alerts so the list, facets and KPI strip share the alert scope', () => {
    expect(buildVentasMLFilterParams(BASE_FILTERS).only_alerts).toBe(false);
    expect(buildVentasMLFilterParams({ ...BASE_FILTERS, onlyAlerts: true }).only_alerts).toBe(true);
  });

  it('reflects a toggle turned off', () => {
    const params = buildVentasMLFilterParams({ ...BASE_FILTERS, includeUnknown: false, includeMixed: false });
    expect(params.include_unknown).toBe(false);
    expect(params.include_mixed).toBe(false);
    expect(params.include_in_dispute).toBe(true);
    expect(params.include_provisional).toBe(true);
  });
});
