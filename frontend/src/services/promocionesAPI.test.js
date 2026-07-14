import { describe, it, expect, vi, beforeEach } from 'vitest';

// The global test/setup.js mocks '../services/api' wholesale (without the
// FE-C write methods). Unmock it here so THIS file exercises the real
// module (with axios itself mocked below) instead of that global stub.
vi.unmock('../services/api');

const mockApi = {
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
};

vi.mock('axios', () => ({
  default: {
    create: () => mockApi,
  },
}));

describe('promocionesAPI (write methods, FE-C)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('postPromocionItem posts to /promociones/item/{mla} with the given body', async () => {
    const { promocionesAPI } = await import('./api');
    mockApi.post.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });

    await promocionesAPI.postPromocionItem('MLA123', { promotion_id: 'P1', promotion_type: 'DEAL' });

    expect(mockApi.post).toHaveBeenCalledWith('/promociones/item/MLA123', {
      promotion_id: 'P1',
      promotion_type: 'DEAL',
    });
  });

  it('deletePromocionItem deletes /promociones/item/{mla} with the given params', async () => {
    const { promocionesAPI } = await import('./api');
    mockApi.delete.mockResolvedValue({ data: { status: 'submitted' } });

    await promocionesAPI.deletePromocionItem('MLA123', { promotion_id: 'P1', promotion_type: 'DEAL' });

    expect(mockApi.delete).toHaveBeenCalledWith('/promociones/item/MLA123', {
      params: { promotion_id: 'P1', promotion_type: 'DEAL' },
    });
  });

  it('getMarkupParaPrecio gets /promociones/item/{mla}/markup with the given price', async () => {
    const { promocionesAPI } = await import('./api');
    mockApi.get.mockResolvedValue({ data: { price: 850, nuestro_markup: 18.5 } });

    await promocionesAPI.getMarkupParaPrecio('MLA123', 850);

    expect(mockApi.get).toHaveBeenCalledWith('/promociones/item/MLA123/markup', {
      params: { price: 850 },
    });
  });
});
