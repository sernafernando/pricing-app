/**
 * vpf-metricas-canal-fe T2 (S5, S6, C3, C4): the board's channel (ML / Por fuera / Todo) -- which ones a viewer may
 * use, the margin each one needs, how a link carries it and what the board is asked for.
 */
import { describe, it, expect } from 'vitest';
import {
  canalesPermitidos,
  canalInicial,
  formatPdfStamp,
  formatPorTipo,
  margenPermitido,
} from './metricasMlCanal';
import { defaultView, readMetricasUrl, writeMetricasUrl } from './metricasMlUrl';
import { buildMetricasMLParams } from './metricasMlParams';

const conPermisos = (...codes) => (code) => codes.includes(code);
const TODAY = new Date(2026, 9, 27);
const SORT_KEYS = new Set(['gross']);
const read = (query, canales) =>
  readMetricasUrl(new URLSearchParams(query), { sortKeys: SORT_KEYS, today: TODAY, ...(canales ? { canales } : {}) });

describe('canalesPermitidos (S5 / C4)', () => {
  it('ML needs ml_metricas.ver, Por fuera needs ventas_fuera.ver_metricas_pdf, Todo needs both', () => {
    expect(canalesPermitidos(conPermisos('ml_metricas.ver'))).toEqual(['ml']);
    expect(canalesPermitidos(conPermisos('ventas_fuera.ver_metricas_pdf'))).toEqual(['fuera']);
    expect(canalesPermitidos(conPermisos('ml_metricas.ver', 'ventas_fuera.ver_metricas_pdf'))).toEqual(['ml', 'fuera', 'todo']);
    expect(canalesPermitidos(conPermisos())).toEqual([]);
  });

  it('a tplink.solo viewer keeps ML only (the board answers 403 to fuera and todo)', () => {
    expect(canalesPermitidos(conPermisos('ml_metricas.ver', 'ventas_fuera.ver_metricas_pdf'), { tpSolo: true })).toEqual(['ml']);
  });

  it('a PDF-only viewer is locked to Por fuera whatever the link says', () => {
    expect(canalInicial('ml', ['fuera'])).toBe('fuera');
    expect(canalInicial('todo', ['fuera'])).toBe('fuera');
    expect(canalInicial('todo', ['ml', 'fuera', 'todo'])).toBe('todo');
    expect(canalInicial('fuera', ['ml'])).toBe('ml');
  });
});

describe('margenPermitido (S6)', () => {
  it('ML needs ml_metricas.ver_ganancia, Por fuera ventas_fuera.ver_ganancia, Todo both', () => {
    const ml = conPermisos('ml_metricas.ver_ganancia');
    const fuera = conPermisos('ventas_fuera.ver_ganancia');
    const ambos = conPermisos('ml_metricas.ver_ganancia', 'ventas_fuera.ver_ganancia');
    expect([margenPermitido('ml', ml), margenPermitido('fuera', ml), margenPermitido('todo', ml)]).toEqual([true, false, false]);
    expect([margenPermitido('ml', fuera), margenPermitido('fuera', fuera), margenPermitido('todo', fuera)]).toEqual([false, true, false]);
    expect(margenPermitido('todo', ambos)).toBe(true);
  });
});

describe('formatters', () => {
  it('the document types read "104 Fc A · 54 Fc B · 6 Nc A"', () => {
    expect(
      formatPorTipo([
        { tipo: 'FC', letra: 'A', cantidad: 104 },
        { tipo: 'FC', letra: 'B', cantidad: 54 },
        { tipo: 'NC', letra: 'A', cantidad: 6 },
      ]),
    ).toBe('104 Fc A · 54 Fc B · 6 Nc A');
    expect(formatPorTipo([])).toBe('');
  });

  it('a PDF upload stamp reads dd/mm hh:mm in local time', () => {
    expect(formatPdfStamp(new Date(2026, 10, 16, 12, 10).toISOString())).toBe('16/11 12:10');
    expect(formatPdfStamp(null)).toBeNull();
  });
});

describe('metricasMlUrl: canal, costo, empresas, vendedores', () => {
  it('keeps every existing URL as it was: ML and Costo D are defaults and never written', () => {
    const defaults = defaultView(TODAY);
    expect(defaults).toMatchObject({ canal: 'ml', costo: 'costo_d', empresas: [], vendedores: [] });
    expect(writeMetricasUrl(defaults).toString()).toBe('');
  });

  it('?canal=fuera opens Por fuera; canal, costo, empresas and vendedores round-trip', () => {
    expect(read('canal=fuera').canal).toBe('fuera');
    const view = { ...defaultView(TODAY), canal: 'todo', costo: 'costo', empresas: ['Empresa Norte'], vendedores: ['Vendedora Uno', 'Vendedor Dos'] };
    const query = writeMetricasUrl(view).toString();
    expect(query).toBe('canal=todo&costo=costo&empresas=Empresa+Norte&vendedores=Vendedora+Uno%2CVendedor+Dos');
    expect(read(query)).toEqual(view);
  });

  it('drops an unknown canal or costo, and a canal the viewer may not use', () => {
    expect(read('canal=otro&costo=x')).toMatchObject({ canal: 'ml', costo: 'costo_d' });
    expect(read('canal=todo', ['ml']).canal).toBe('ml');
    expect(read('', ['fuera']).canal).toBe('fuera');
  });

  it('Por fuera has no publication view: a link with agrupar=publication opens by product', () => {
    expect(read('canal=fuera&agrupar=publication').groupBy).toBe('product');
    expect(read('canal=todo&agrupar=publication').groupBy).toBe('publication');
  });

  it('reads the "Sin producto" alert', () => {
    expect(read('canal=fuera&alertas=sin_producto').alerts).toEqual(['sin_producto']);
  });
});

const BASE = {
  fechaDesde: '2026-09-01',
  fechaHasta: '2026-09-30',
  compararCon: 'periodo_anterior',
  groupBy: 'product',
  searchQuery: '',
  productFilters: { marcas: [], categorias: [], subcategorias: [], pms: [] },
  storeFilter: '57997',
  pubStatus: ['active'],
  pubType: ['premium'],
  alerts: [],
  soloConVentas: true,
};

describe('buildMetricasMLParams: canal (C3)', () => {
  it('canal=ml sends exactly what it sent before: no canal, costo, empresas nor vendedores', () => {
    const params = buildMetricasMLParams({ ...BASE, canal: 'ml', costo: 'costo', empresas: ['E'], vendedores: ['V'], alerts: ['sin_producto', 'sin_ventas_30d'] });
    expect(params).not.toHaveProperty('canal');
    expect(params).not.toHaveProperty('costo');
    expect(params).not.toHaveProperty('empresas');
    expect(params).not.toHaveProperty('vendedores');
    expect(params.alerts).toBe('sin_ventas_30d');
    expect(buildMetricasMLParams(BASE)).toEqual(buildMetricasMLParams({ ...BASE, canal: 'ml' }));
  });

  it('canal=todo sends canal, costo, empresas and vendedores, and keeps the ML-only filters', () => {
    const params = buildMetricasMLParams({ ...BASE, canal: 'todo', costo: 'costo_d', empresas: ['Empresa Norte'], vendedores: ['Vendedora Uno'], alerts: ['sin_producto'] });
    expect(params).toMatchObject({
      canal: 'todo',
      costo: 'costo_d',
      empresas: 'Empresa Norte',
      vendedores: 'Vendedora Uno',
      stores: '57997',
      pub_status: 'active',
      pub_type: 'premium',
      alerts: 'sin_producto',
    });
  });

  it('canal=fuera leaves out the ML-only filters (tienda, publicación) and the ML-only alerts', () => {
    const params = buildMetricasMLParams({ ...BASE, canal: 'fuera', costo: 'costo', alerts: ['sin_ventas_30d', 'sin_producto', 'margen_cayendo'] });
    expect(params).toMatchObject({ canal: 'fuera', costo: 'costo', alerts: 'sin_producto,margen_cayendo' });
    expect(params).not.toHaveProperty('stores');
    expect(params).not.toHaveProperty('pub_status');
    expect(params).not.toHaveProperty('pub_type');
    expect(params).not.toHaveProperty('empresas');
  });
});
