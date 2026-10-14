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

describe('pricePermissions', () => {
  it('a Productos editor writes every price', () => {
    for (const code of ['productos.editar_precio_clasica', 'productos.editar_precio_cuotas', 'productos.toggle_rebate', 'productos.toggle_web_transferencia']) {
      expect(pricePermissions(holding(code))).toEqual({ canEditClasica: true, canEditMlCuotas: true, canEditPvp: true });
    }
  });

  it('a Tienda editor writes only the ML instalments (set-cuota, lista web)', () => {
    for (const code of ['tienda.editar_precio_gremio', 'tienda.editar_precio_web_transf']) {
      expect(pricePermissions(holding(code))).toEqual({ canEditClasica: false, canEditMlCuotas: true, canEditPvp: false });
    }
  });

  it('productos.ver alone writes nothing', () => {
    expect(pricePermissions(holding('productos.ver'))).toEqual({ canEditClasica: false, canEditMlCuotas: false, canEditPvp: false });
  });
});
