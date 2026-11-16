/**
 * Tactical list helpers (owner, 2026-11-04, S7: "el tactical tiene que podersele cargar una marca adjunta para después
 * poder filtrar por marca"). Amounts, dates, state and progress as the list design shows them.
 */
import { describe, expect, it } from 'vitest';
import {
  alcanceDe,
  avanceDeLinea,
  avanceDeTactical,
  FILTROS_VACIOS,
  estadoDe,
  formatMontoTactical,
  formatMontosKpi,
  paramsDeFiltros,
  valorDeLinea,
  vigenciaDe,
} from './tacticalsFormat';

const HOY = new Date(2026, 10, 12);

describe('valorDeLinea', () => {
  it('shows a per-unit amount, a percentage and a total in the tactical currency', () => {
    expect(valorDeLinea({ modo_monto: 'por_unidad', valor: '220', moneda: 'USD' })).toBe('USD 220 / u');
    expect(valorDeLinea({ modo_monto: 'porcentaje', valor: '3.5', moneda: 'ARS' })).toBe('3,5 %');
    expect(valorDeLinea({ modo_monto: 'monto_total', valor: '3000', moneda: 'USD' })).toBe('USD 3.000');
  });

  it('shows a sell in total loaded in USD with its ARS total and the fixed rate (S4)', () => {
    expect(
      valorDeLinea({ modo_monto: 'monto_total', valor: '1200610.01', moneda: 'ARS', valor_usd: '1200.01' }, '1000.5'),
    ).toBe(`USD 1.200,01 → ${valorDeLinea({ modo_monto: 'monto_total', valor: '1200610.01', moneda: 'ARS' })} (TC 1.000,5)`);
  });
});

describe('formatMontoTactical', () => {
  it('writes the currency code and es-AR thousands, and a dash when empty', () => {
    expect(formatMontoTactical('1240000', 'ARS')).toBe('ARS 1.240.000');
    expect(formatMontoTactical(12.5, 'USD')).toBe('USD 12,5');
    expect(formatMontoTactical(null, 'USD')).toBe('—');
  });
});

describe('vigenciaDe', () => {
  it('writes the start without year and the end with it', () => {
    expect(vigenciaDe('2026-11-01', '2026-11-30')).toBe('01/11 al 30/11/2026');
    expect(vigenciaDe('2026-11-01', '2027-01-31')).toBe('01/11 al 31/01/2027');
  });
});

describe('estadoDe', () => {
  it('is Anulado, Vencido, Vence en N días (7 or fewer) or Vigente', () => {
    expect(estadoDe({ estado: 'anulado', fecha_hasta: '2026-11-30' }, HOY)).toEqual({ texto: 'Anulado', tono: 'neutral' });
    expect(estadoDe({ estado: 'activo', fecha_hasta: '2026-11-11' }, HOY)).toEqual({ texto: 'Vencido', tono: 'neutral' });
    expect(estadoDe({ estado: 'activo', fecha_hasta: '2026-11-15' }, HOY)).toEqual({ texto: 'Vence en 3 días', tono: 'warning' });
    expect(estadoDe({ estado: 'activo', fecha_hasta: '2026-11-13' }, HOY)).toEqual({ texto: 'Vence en 1 día', tono: 'warning' });
    expect(estadoDe({ estado: 'activo', fecha_hasta: '2026-11-12' }, HOY)).toEqual({ texto: 'Vence hoy', tono: 'warning' });
    expect(estadoDe({ estado: 'activo', fecha_hasta: '2026-11-20' }, HOY)).toEqual({ texto: 'Vigente', tono: 'success' });
  });
});

describe('alcanceDe', () => {
  it('says which invoices of the operation an invoice line covers (varias facturas S5)', () => {
    const linea = { alcance: 'factura', pedido_compra_id: 5521, pedido_numero: 'OC-1840', facturas_ct: null, facturas_elegidas: null };
    expect(alcanceDe(linea).titulo).toBe('Factura del pedido OC-1840 · Todas las facturas');
    const elegidas = [
      { ct_transaction_id: 70001, numero: 'A-0001-123' },
      { ct_transaction_id: 70003, numero: null },
    ];
    expect(alcanceDe({ ...linea, facturas_ct: [70001, 70003], facturas_elegidas: elegidas }).titulo).toBe(
      'Factura del pedido OC-1840 · A-0001-123, CT 70003',
    );
  });


  it('names a brand, a category or an invoice line; product lines are chips', () => {
    expect(alcanceDe({ alcance: 'marca', marca: 'HP' })).toEqual({ titulo: 'Marca HP', detalle: 'Todos los productos de la marca' });
    expect(alcanceDe({ alcance: 'marca', marca: 'TP-LINK', categoria: 'Routers' })).toEqual({
      titulo: 'Marca TP-LINK · Routers',
      detalle: 'Los productos de la marca en esa categoría',
    });
    expect(alcanceDe({ alcance: 'categoria', categoria: 'Monitores' })).toEqual({
      titulo: 'Categoría Monitores',
      detalle: 'Todos los productos de la categoría',
    });
    expect(alcanceDe({ alcance: 'factura', pedido_compra_id: 5521, pedido_numero: 'OC-1840' })).toEqual({
      titulo: 'Factura del pedido OC-1840 · Todas las facturas',
      detalle: null,
    });
    expect(alcanceDe({ alcance: 'factura', pedido_compra_id: 5521, pedido_numero: null })).toEqual({
      titulo: 'Factura del pedido #5521 · Todas las facturas',
      detalle: null,
    });
  });
});

describe('avanceDeLinea', () => {
  it('measures the unit cap first, then the money cap, and marks warning and full', () => {
    expect(avanceDeLinea({ tope_unidades: 90, unidades_usadas: 58 })).toEqual({ porcentaje: 64.4, tono: 'normal' });
    expect(avanceDeLinea({ tope_unidades: 180, unidades_usadas: 172 })).toEqual({ porcentaje: 95.6, tono: 'warn' });
    expect(avanceDeLinea({ tope_unidades: 120, unidades_usadas: 108 })).toEqual({ porcentaje: 90, tono: 'normal' });
    expect(avanceDeLinea({ tope_unidades: 62, unidades_usadas: 62 })).toEqual({ porcentaje: 100, tono: 'full' });
    expect(avanceDeLinea({ tope_unidades: null, tope_monto: '2000', monto_usado: '500' })).toEqual({ porcentaje: 25, tono: 'normal' });
    expect(avanceDeLinea({ tope_unidades: null, tope_monto: null, monto_usado: '500' })).toBeNull();
  });

  it('a line one short of its cap is not full, even when the percentage rounds to 100', () => {
    expect(avanceDeLinea({ tope_unidades: 2500, unidades_usadas: 2499 })).toEqual({ porcentaje: 99.9, tono: 'warn' });
  });

  it('a zero cap has nothing to measure', () => {
    expect(avanceDeLinea({ tope_unidades: 0, unidades_usadas: 0 })).toBeNull();
    expect(avanceDeTactical([{ tope_unidades: 0, unidades_usadas: 0, tope_monto: null, monto_usado: '0' }]).unidades).toBeNull();
  });
});

describe('avanceDeTactical', () => {
  it('adds units over the lines with a unit cap and money over all lines', () => {
    const lineas = [
      { tope_unidades: 90, unidades_usadas: 58, tope_monto: null, monto_usado: '12760', moneda: 'USD' },
      { tope_unidades: 300, unidades_usadas: 132, tope_monto: '3000', monto_usado: '1584', moneda: 'USD' },
      { tope_unidades: null, unidades_usadas: 7, tope_monto: null, monto_usado: '100', moneda: 'USD' },
    ];
    expect(avanceDeTactical(lineas)).toEqual({
      unidades: { usadas: 190, tope: 390, porcentaje: 48.7, tono: 'normal' },
      monto: 'USD 14.444',
    });
  });

  it('gives the money cap only when every line has one, and no units when no line caps them', () => {
    const lineas = [
      { tope_unidades: null, tope_monto: '1000', monto_usado: '400', moneda: 'USD' },
      { tope_unidades: null, tope_monto: '500', monto_usado: '100', moneda: 'USD' },
    ];
    expect(avanceDeTactical(lineas)).toEqual({ unidades: null, monto: 'USD 500 de USD 1.500' });
  });

  it('keeps each currency apart: a USD tactical can hold an ARS cost-reduction line', () => {
    const lineas = [
      { tope_unidades: null, tope_monto: null, monto_usado: '300', moneda: 'USD' },
      { tope_unidades: null, tope_monto: '50000', monto_usado: '12000', moneda: 'ARS' },
    ];
    expect(avanceDeTactical(lineas)).toEqual({ unidades: null, monto: 'USD 300 · ARS 12.000 de ARS 50.000' });
  });
});

describe('paramsDeFiltros', () => {
  it('sends only what is set, with Todos as no tipo', () => {
    expect(
      paramsDeFiltros({ tipo: 'todos', marca: '', moneda: '', estado: 'vigentes', desde: '', hasta: '', q: '' }, { page: 1, pageSize: 50 }),
    ).toEqual({ estado: 'vigentes', page: 1, page_size: 50 });
    expect(
      paramsDeFiltros(
        { tipo: 'sell_out', marca: 'HP', moneda: 'USD', estado: 'anulados', desde: '2026-11-01', hasta: '2026-11-30', q: ' bps ' },
        { page: 2, pageSize: 25 },
      ),
    ).toEqual({ tipo: 'sell_out', marca: 'HP', moneda: 'USD', estado: 'anulados', desde: '2026-11-01', hasta: '2026-11-30', q: 'bps', page: 2, page_size: 25 });
  });

  it('sends Contiene and the product search only when set, the search trimmed (SISO S1, S2)', () => {
    const base = { tipo: 'todos', marca: '', moneda: '', estado: 'vigentes', desde: '', hasta: '', q: '' };
    expect(paramsDeFiltros({ ...base, contiene: '', producto: '  ' }, { page: 1, pageSize: 50 })).toEqual({
      estado: 'vigentes', page: 1, page_size: 50,
    });
    expect(paramsDeFiltros({ ...base, contiene: 'factura', producto: ' RE200 ' }, { page: 1, pageSize: 50 })).toEqual({
      estado: 'vigentes', contiene: 'factura', producto: 'RE200', page: 1, page_size: 50,
    });
  });
});

describe('an invoice tactical (factura sin fecha S4)', () => {
  it('shows Por factura instead of a range and is current until voided', () => {
    expect(vigenciaDe('2025-03-10', '2026-03-10', true)).toBe('Por factura');
    expect(estadoDe({ estado: 'activo', fecha_hasta: '2026-03-10', por_factura: true }, HOY)).toEqual({
      texto: 'Vigente',
      tono: 'success',
    });
    expect(estadoDe({ estado: 'anulado', fecha_hasta: '2026-03-10', por_factura: true }, HOY).texto).toBe('Anulado');
  });
});

describe('cobranza filter and KPIs (tactical cobranza S4)', () => {
  it('sends cobranza only when it is not Todos', () => {
    expect(FILTROS_VACIOS.cobranza).toBe('todos');
    expect(paramsDeFiltros(FILTROS_VACIOS, { page: 1, pageSize: 50 })).not.toHaveProperty('cobranza');
    expect(paramsDeFiltros({ ...FILTROS_VACIOS, cobranza: 'cobrados' }, { page: 1, pageSize: 50 })).toMatchObject({ cobranza: 'cobrados' });
  });

  it('formats a KPI amount per currency, a dash when there is none', () => {
    expect(formatMontosKpi([{ moneda: 'ARS', monto: '4380250.00' }, { moneda: 'USD', monto: '1920.50' }])).toBe('ARS 4.380.250 · USD 1.920,5');
    expect(formatMontosKpi([])).toBe('—');
  });

  it('formats a KPI amount as generated of cap when its currency has a cap (S6)', () => {
    const montos = [{ moneda: 'ARS', monto: '4380250.00', tope: '6000000.00' }, { moneda: 'USD', monto: '1920.00', tope: null }];
    expect(formatMontosKpi(montos)).toBe('ARS 4.380.250 de 6.000.000 · USD 1.920');
  });

  it('shows the cap apart when only some lines of the currency have one (advisory on #2195)', () => {
    const montos = [{ moneda: 'ARS', monto: '900.00', tope: '500.00', tope_parcial: true }];
    expect(formatMontosKpi(montos)).toBe('ARS 900 · tope 500 (líneas con tope)');
  });
});

describe('an invoice line waiting for its invoice (sell in factura pendiente S4)', () => {
  it('shows Esperando factura on the tactical until the invoice is linked, then the normal state', () => {
    const esperando = { estado: 'activo', fecha_hasta: '2026-11-12', por_factura: true, esperando_factura: true };
    expect(estadoDe(esperando, HOY)).toEqual({ texto: 'Esperando factura', tono: 'warning' });
    expect(estadoDe({ ...esperando, esperando_factura: false }, HOY)).toEqual({ texto: 'Vigente', tono: 'success' });
    expect(estadoDe({ ...esperando, estado: 'anulado' }, HOY).texto).toBe('Anulado');
  });

  it('says on the line that it waits for the invoice', () => {
    const linea = { alcance: 'factura', pedido_compra_id: 9, pedido_numero: 'OC-9', esperando_factura: true };
    expect(alcanceDe(linea)).toEqual({
      titulo: 'Factura del pedido OC-9 · Todas las facturas',
      detalle: 'Esperando factura: se aplica cuando Compras vincule la factura del proveedor',
    });
    expect(alcanceDe({ ...linea, esperando_factura: false }).detalle).toBeNull();
  });
});
