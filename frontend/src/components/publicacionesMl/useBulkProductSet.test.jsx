/**
 * The products a bulk action acts on: a stale answer never lands, and each failure says why there is no set.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import useBulkProductSet from './useBulkProductSet';
import { publicacionesMlAPI } from '../../services/api';

vi.mock('../../services/api', () => ({
  publicacionesMlAPI: { productIds: vi.fn() },
}));

/** A response the test settles by hand; it ignores the abort signal, like a server answer already in flight. */
function deferred() {
  let resolve;
  const promise = new Promise((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const body = (itemIds) => ({ data: { item_ids: itemIds, count: itemIds.length, sin_producto: 0, fuera_de_catalogo: 0 } });

describe('useBulkProductSet', () => {
  beforeEach(() => vi.clearAllMocks());

  it('a slower earlier answer arriving after a filter change never lands: the later set wins', async () => {
    const earlier = deferred();
    const later = deferred();
    publicacionesMlAPI.productIds.mockReturnValueOnce(earlier.promise).mockReturnValueOnce(later.promise);
    const { result, rerender } = renderHook(({ params }) => useBulkProductSet(params, true), {
      initialProps: { params: { estado: 'active' } },
    });
    rerender({ params: { estado: 'paused' } });
    expect(publicacionesMlAPI.productIds).toHaveBeenCalledTimes(2);

    await act(async () => later.resolve(body([2001, 2002])));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    await act(async () => earlier.resolve(body([1001])));

    expect(result.current.itemIds).toEqual([2001, 2002]);
  });

  it('a timeout (503) gives its own reason, not the generic one', async () => {
    publicacionesMlAPI.productIds.mockRejectedValue({ response: { status: 503, data: {} } });
    const { result } = renderHook(() => useBulkProductSet({ estado: 'active' }, true));
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toBe('La consulta tardó demasiado: acotá los filtros o reintentá.');
    expect(result.current.itemIds).toEqual([]);
  });
});
