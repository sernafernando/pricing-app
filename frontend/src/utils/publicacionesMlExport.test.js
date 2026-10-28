import { describe, it, expect, vi, beforeEach } from 'vitest';
import { publicacionesMlAPI } from '../services/api';
import { resolverProductosExport } from './publicacionesMlExport';

vi.mock('../services/api', () => ({
  publicacionesMlAPI: { productIds: vi.fn() },
}));

const refused = (status, error) => Object.assign(new Error('refused'), { response: { status, data: { error } } });

beforeEach(() => vi.clearAllMocks());

describe('resolverProductosExport', () => {
  it("asks the bulk resolver with the list's params and returns its products", async () => {
    publicacionesMlAPI.productIds.mockResolvedValue({ data: { item_ids: [4, 9], count: 2, sin_producto: 1 } });

    await expect(resolverProductosExport({ marca: 'X' })).resolves.toEqual([4, 9]);
    expect(publicacionesMlAPI.productIds).toHaveBeenCalledWith({ marca: 'X' });
  });

  it('refuses an empty set: an export never reads it as "all"', async () => {
    publicacionesMlAPI.productIds.mockResolvedValue({ data: { item_ids: [], count: 0, sin_producto: 3 } });

    await expect(resolverProductosExport({})).rejects.toThrow(
      'Las publicaciones filtradas no tienen productos vinculados para exportar.',
    );
  });

  it('an answer without a product list is refused, never read as a set', async () => {
    publicacionesMlAPI.productIds.mockResolvedValue({ data: {} });

    await expect(resolverProductosExport({})).rejects.toThrow('No se pudieron obtener los productos de los filtros.');
  });

  it('over the cap names the count and the cap of an export', async () => {
    publicacionesMlAPI.productIds.mockRejectedValue(
      refused(422, { code: 'demasiados_productos', message: 'una acción masiva admite hasta 10000', count: 12000, max: 10000 }),
    );

    await expect(resolverProductosExport({})).rejects.toThrow(
      'El filtro selecciona 12000 productos; una exportación admite hasta 10000. Acotá el filtro.',
    );
  });

  it("another 422 keeps the server's message", async () => {
    publicacionesMlAPI.productIds.mockRejectedValue(refused(422, { code: 'filtro_invalido', message: 'evento: requires the events flag' }));

    await expect(resolverProductosExport({})).rejects.toThrow('evento: requires the events flag');
  });

  it('a slow query asks to narrow or retry', async () => {
    publicacionesMlAPI.productIds.mockRejectedValue(refused(503, { code: 'consulta_lenta', message: 'slow' }));

    await expect(resolverProductosExport({})).rejects.toThrow('La consulta tardó demasiado: acotá los filtros o reintentá.');
  });

  it('anything else is a generic reason', async () => {
    publicacionesMlAPI.productIds.mockRejectedValue(new Error('Network Error'));

    await expect(resolverProductosExport({})).rejects.toThrow('No se pudieron obtener los productos de los filtros.');
  });
});
