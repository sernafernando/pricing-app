/**
 * Tactical list helpers (owner, 2026-11-04, S7: "el tactical tiene que podersele cargar una marca adjunta para después
 * poder filtrar por marca"). Amounts, dates, state and progress as the list design shows them.
 */
import { describe, expect, it } from 'vitest';
import {
  alcanceDe,
  avanceDeLinea,
  avanceDeTactical,
  estadoDe,
  formatMontoTactical,
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
  it('names a brand, a category or an invoice line; product lines are chips', () => {
    expect(alcanceDe({ alcance: 'marca', marca: 'HP' })).toEqual({ titulo: 'Marca HP', detalle: 'Todos los productos de la marca' });
    expect(alcanceDe({ alcance: 'categoria', categoria: 'Monitores' })).toEqual({
      titulo: 'Categoría Monitores',
      detalle: 'Todos los productos de la categoría',
    });
    expect(alcanceDe({ alcance: 'factura', pedido_compra_id: 5521, pedido_numero: 'OC-1840' })).toEqual({
      titulo: 'Factura del pedido OC-1840',
      detalle: null,
    });
    expect(alcanceDe({ alcance: 'factura', pedido_compra_id: 5521, pedido_numero: null })).toEqual({
      titulo: 'Factura del pedido #5521',
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
      paramsDeFiltros({ tipo: 'todos', marca: '', estado: 'vigentes', desde: '', hasta: '', q: '' }, { page: 1, pageSize: 50 }),
    ).toEqual({ estado: 'vigentes', page: 1, page_size: 50 });
    expect(
      paramsDeFiltros(
        { tipo: 'sell_out', marca: 'HP', estado: 'anulados', desde: '2026-11-01', hasta: '2026-11-30', q: ' bps ' },
        { page: 2, pageSize: 25 },
      ),
    ).toEqual({ tipo: 'sell_out', marca: 'HP', estado: 'anulados', desde: '2026-11-01', hasta: '2026-11-30', q: 'bps', page: 2, page_size: 25 });
  });
});
