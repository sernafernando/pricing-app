import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { usePxqMarkup } from './usePxqMarkup';
import { pxqAPI } from '../services/api';

vi.mock('../services/api', () => ({
  pxqAPI: {
    getMarkup: vi.fn(),
  },
}));

function setup() {
  return { current: new Map() };
}

describe('usePxqMarkup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches GET /pxq/{item_id}/markup and indexes the response by tier_id', async () => {
    const cacheRef = setup();
    pxqAPI.getMarkup.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        tiers: [
          { tier_id: 1, markup: 0.25, limpio: 1000, comision_total: 150 },
          { tier_id: 2, reason: 'shipping_unavailable' },
        ],
      },
    });

    const { result } = renderHook(() => usePxqMarkup(cacheRef, 'MLA001', true));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(pxqAPI.getMarkup).toHaveBeenCalledWith('MLA001');
    expect(result.current.data.get(1)).toEqual({ tier_id: 1, markup: 0.25, limpio: 1000, comision_total: 150 });
    expect(result.current.data.get(2)).toEqual({ tier_id: 2, reason: 'shipping_unavailable' });
    expect(result.current.error).toBeNull();
  });

  it('never calls the network when canRead is false, same gating PxqPanel applies to getLive', async () => {
    const cacheRef = setup();

    const { result } = renderHook(() => usePxqMarkup(cacheRef, 'MLA001', false));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(pxqAPI.getMarkup).not.toHaveBeenCalled();
    expect(result.current.data).toBeNull();
  });

  it('an empty tiers array indexes to an empty map, not null', async () => {
    const cacheRef = setup();
    pxqAPI.getMarkup.mockResolvedValue({ data: { item_id: 'MLA001', tiers: [] } });

    const { result } = renderHook(() => usePxqMarkup(cacheRef, 'MLA001', true));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toBeInstanceOf(Map);
    expect(result.current.data.size).toBe(0);
  });

  it('surfaces a fetch failure as error without throwing', async () => {
    const cacheRef = setup();
    const err = new Error('network');
    pxqAPI.getMarkup.mockRejectedValue(err);

    const { result } = renderHook(() => usePxqMarkup(cacheRef, 'MLA001', true));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe(err);
    expect(result.current.data).toBeNull();
  });

  it('reload() re-fetches and overwrites the cache', async () => {
    const cacheRef = setup();
    pxqAPI.getMarkup
      .mockResolvedValueOnce({ data: { item_id: 'MLA001', tiers: [{ tier_id: 1, markup: 0.1 }] } })
      .mockResolvedValueOnce({ data: { item_id: 'MLA001', tiers: [{ tier_id: 1, markup: 0.2 }] } });

    const { result } = renderHook(() => usePxqMarkup(cacheRef, 'MLA001', true));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data.get(1).markup).toBe(0.1);

    await result.current.reload();

    await waitFor(() => expect(result.current.data.get(1).markup).toBe(0.2));
    expect(pxqAPI.getMarkup).toHaveBeenCalledTimes(2);
  });
});
