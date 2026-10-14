import { describe, it, expect } from 'vitest';
import { canViewProductPrices } from './productPricePermissions';

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
