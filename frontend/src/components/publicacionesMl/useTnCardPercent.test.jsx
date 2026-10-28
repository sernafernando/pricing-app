/**
 * useTnCardPercent (S3): the Tienda Nube card surcharge Productos reads for its "transf." hint.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import api from '../../services/api';
import useTnCardPercent from './useTnCardPercent';

vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

describe('useTnCardPercent', () => {
  it("reads Productos' config value once", async () => {
    api.get.mockResolvedValue({ data: { valor: 25 } });
    const { result, rerender } = renderHook(() => useTnCardPercent());
    expect(result.current).toBeNull();
    await waitFor(() => expect(result.current).toBe(25));
    rerender();
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledWith('/markups-tienda/config/porcentaje_tarjeta_tn');
  });

  it("asks nothing for who does not see Productos' prices", () => {
    renderHook(() => useTnCardPercent(false));
    expect(api.get).not.toHaveBeenCalled();
  });

  it('stays null when the read fails: no hint rather than a wrong one', async () => {
    let fail;
    api.get.mockReturnValue(new Promise((_, reject) => (fail = reject)));
    const { result } = renderHook(() => useTnCardPercent());
    // The rejection and its handler run before the assertion, not just the request.
    await act(async () => {
      fail(new Error('boom'));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(result.current).toBeNull();
  });
});
