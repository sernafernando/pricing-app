import { describe, it, expect, vi, beforeEach } from 'vitest';

// setup.js globally mocks '../services/api' with plain vi.fn() stubs (needed
// by page-level tests). This suite verifies the REAL implementation's URL
// wiring, so it unmocks the module and mocks axios directly instead.
vi.unmock('../services/api');

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockUse = vi.fn();

vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: mockGet,
      post: mockPost,
      interceptors: {
        request: { use: mockUse },
        response: { use: mockUse },
      },
    }),
  },
}));

describe('productosAPI.getProductoMercadolibre / promocionesAPI.getPromocionesItem', () => {
  beforeEach(() => {
    vi.resetModules();
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it('getProductoMercadolibre calls GET /productos/{item_id}/mercadolibre', async () => {
    const { productosAPI } = await import('./api');
    productosAPI.getProductoMercadolibre('ITEM001');
    expect(mockGet).toHaveBeenCalledWith('/productos/ITEM001/mercadolibre');
  });

  it('getProductoMercadolibreLite calls GET /productos/{item_id}/mercadolibre?lite=true', async () => {
    const { productosAPI } = await import('./api');
    productosAPI.getProductoMercadolibreLite('ITEM001');
    expect(mockGet).toHaveBeenCalledWith('/productos/ITEM001/mercadolibre?lite=true');
  });

  it('getPromocionesItem calls GET /promociones/item/{mla_id}', async () => {
    const { promocionesAPI } = await import('./api');
    promocionesAPI.getPromocionesItem('MLA123');
    expect(mockGet).toHaveBeenCalledWith('/promociones/item/MLA123');
  });
});
