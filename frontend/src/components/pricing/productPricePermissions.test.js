import { describe, it, expect } from 'vitest';
import { canViewProductPrices, pricePermissions } from './productPricePermissions';

const holding = (...codes) => (code) => codes.includes(code);

describe('canViewProductPrices', () => {
  it.each([
    'productos.ver',
    'productos.editar_precio_clasica',
    'productos.editar_precio_cuotas',
    'productos.toggle_rebate',
    'productos.toggle_web_transferencia',
    'tienda.editar_precio_gremio',
    'tienda.editar_precio_web_transf',
  ])('lets %s see the prices', (code) => {
    expect(canViewProductPrices(holding(code))).toBe(true);
  });

  it('hides them from anybody else', () => {
    expect(canViewProductPrices(holding('promos.ver', 'ml_ops.gestionar'))).toBe(false);
  });
});

const NO_TOGGLES = { canToggleRebate: false, canToggleWebTransf: false, canToggleOutOfCards: false };

describe('pricePermissions', () => {
  it('a Productos editor writes every price', () => {
    for (const code of ['productos.editar_precio_clasica', 'productos.editar_precio_cuotas', 'productos.toggle_rebate', 'productos.toggle_web_transferencia']) {
      expect(pricePermissions(holding(code))).toMatchObject({ canEditClasica: true, canEditMlCuotas: true, canEditPvp: true });
    }
  });

  it('a Tienda editor writes only the ML instalments (set-cuota, lista web)', () => {
    for (const code of ['tienda.editar_precio_gremio', 'tienda.editar_precio_web_transf']) {
      expect(pricePermissions(holding(code))).toEqual({ canEditClasica: false, canEditMlCuotas: true, canEditPvp: false, ...NO_TOGGLES });
    }
  });

  it('productos.ver alone writes nothing', () => {
    expect(pricePermissions(holding('productos.ver'))).toEqual({ canEditClasica: false, canEditMlCuotas: false, canEditPvp: false, ...NO_TOGGLES });
  });

  it.each([
    ['productos.toggle_rebate', 'canToggleRebate'],
    ['productos.toggle_web_transferencia', 'canToggleWebTransf'],
    ['productos.toggle_out_of_cards', 'canToggleOutOfCards'],
  ])('%s, and only it, allows %s (the code its endpoint checks)', (code, flag) => {
    const permissions = pricePermissions(holding(code));
    expect(Object.entries(NO_TOGGLES).map(([key]) => [key, permissions[key]])).toEqual(
      Object.keys(NO_TOGGLES).map((key) => [key, key === flag]),
    );
  });
});
