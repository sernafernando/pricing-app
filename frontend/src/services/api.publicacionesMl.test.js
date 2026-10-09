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

describe('publicacionesMlAPI.variations', () => {
  it('GETs the variations of one publication, with the id URL-encoded', async () => {
    const actual = await vi.importActual('./api');
    const get = vi.spyOn(actual.default, 'get').mockResolvedValue({ data: { variations: [] } });

    await actual.publicacionesMlAPI.variations('MLA 1/2');

    expect(get).toHaveBeenCalledWith('/ml-publications/view/items/MLA%201%2F2/variations');
  });
});

describe('publicacionesMlAPI.events and history', () => {
  it('GETs the events of one publication with the cursor and limit as the query', async () => {
    const actual = await vi.importActual('./api');
    const get = vi.spyOn(actual.default, 'get').mockResolvedValue({ data: { enabled: true, events: [] } });
    const params = { cursor: '2026-10-08T09:30:00.000000Z|9001', limit: 50 };

    await actual.publicacionesMlAPI.events('MLA 1/2', params);

    expect(get).toHaveBeenCalledWith('/ml-publications/view/items/MLA%201%2F2/events', { params });
  });

  it('GETs the history of one publication with the cursor as the query', async () => {
    const actual = await vi.importActual('./api');
    const get = vi.spyOn(actual.default, 'get').mockResolvedValue({ data: { entries: [] } });
    const params = { cursor: '2026-10-08T09:30:00.000000Z|7003' };

    await actual.publicacionesMlAPI.history('MLA1', params);

    expect(get).toHaveBeenCalledWith('/ml-publications/view/items/MLA1/history', { params });
  });
});

describe('publicacionesMlAPI.kpis', () => {
  it('GETs /ml-publications/view/kpis with the params and the abort signal', async () => {
    const actual = await vi.importActual('./api');
    const get = vi.spyOn(actual.default, 'get').mockResolvedValue({ data: { kpis: {} } });
    const params = { estado: 'active', periodo: 30 };
    const { signal } = new AbortController();

    await actual.publicacionesMlAPI.kpis(params, { signal });

    expect(get).toHaveBeenCalledWith('/ml-publications/view/kpis', { params, signal });
  });
});
