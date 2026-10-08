/**
 * publicacionesMlAPI (publicaciones-ml-vista P11a.T3): the client for
 * `GET /ml-publications/view/items`. Run against the REAL module (the global
 * setup replaces it with a stub), with the axios instance's `get` spied on.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';

afterEach(() => vi.restoreAllMocks());

describe('publicacionesMlAPI.items', () => {
  it('GETs /ml-publications/view/items with the params as the query', async () => {
    const actual = await vi.importActual('./api');
    const get = vi.spyOn(actual.default, 'get').mockResolvedValue({ data: { items: [] } });
    const params = { q: 'router', limit: 50, offset: 0, facets: true };

    const response = await actual.publicacionesMlAPI.items(params);

    expect(get).toHaveBeenCalledWith('/ml-publications/view/items', { params });
    expect(response.data).toEqual({ items: [] });
  });
});
