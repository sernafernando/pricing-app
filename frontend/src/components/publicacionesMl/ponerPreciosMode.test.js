import { describe, expect, it } from 'vitest';
import {
  PONER_PRECIOS_COLUMN_KEYS,
  canUsePonerPreciosMode,
  visibilityForPonerPreciosMode,
} from './ponerPreciosMode';

describe('visibilityForPonerPreciosMode', () => {
  it('keeps the S3 preset (and titulo) and hides the rest', () => {
    const keys = [...PONER_PRECIOS_COLUMN_KEYS, 'stock_total', 'facturado_30d', 'evento'];
    expect(visibilityForPonerPreciosMode(keys)).toEqual({
      titulo: true,
      tipo: true,
      estado: true,
      precio: true,
      unidades_7d: true,
      unidades_30d: true,
      markup: true,
      markup_30d: true,
      last_sale: true,
      ageing: true,
      stock_full: true,
      stock_erp: true,
      codigo: true,
      marca: true,
      stock_total: false,
      facturado_30d: false,
      evento: false,
    });
  });

  it('does not invent keys that are not in the table', () => {
    expect(visibilityForPonerPreciosMode(['titulo', 'estado', 'precio'])).toEqual({
      titulo: true,
      estado: true,
      precio: true,
    });
  });
});

describe('canUsePonerPreciosMode', () => {
  it('requires a price-edit permission and promos.escribir', () => {
    const allow = (codes) => (code) => codes.has(code);
    expect(canUsePonerPreciosMode(allow(new Set(['productos.editar_precio_clasica', 'promos.escribir'])))).toBe(
      true,
    );
    expect(canUsePonerPreciosMode(allow(new Set(['productos.editar_precio_clasica'])))).toBe(false);
    expect(canUsePonerPreciosMode(allow(new Set(['promos.escribir'])))).toBe(false);
    expect(canUsePonerPreciosMode(allow(new Set(['tienda.editar_precio_gremio', 'promos.escribir'])))).toBe(true);
  });
});
