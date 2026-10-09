/**
 * `usePublicationDetail` (publicaciones-ml-vista P13c): a silent `refresh`
 * re-reads the detail without ever going back to "loading", so the open tab
 * keeps its state; a late answer for another selection is dropped.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { usePublicationDetail } from './usePublicationDetail';
import { publicacionesMlAPI } from '../../../services/api';
import { DETAIL_RESPONSE } from '../../../test/visual/publicacionesMlFixtures';

vi.mock('../../../services/api', () => ({ publicacionesMlAPI: { detail: vi.fn() } }));

const withPrice = (price) => ({ ...DETAIL_RESPONSE, row: { ...DETAIL_RESPONSE.row, price } });
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

beforeEach(() => publicacionesMlAPI.detail.mockReset());

describe('refresh', () => {
  it('re-reads the detail while staying ready, then shows the new data', async () => {
    publicacionesMlAPI.detail.mockResolvedValueOnce({ data: withPrice(100) });
    const { result } = renderHook(() => usePublicationDetail('MLA1', { canSeeMargin: false }));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const before = result.current.detail;

    const pending = deferred();
    publicacionesMlAPI.detail.mockReturnValueOnce(pending.promise);
    act(() => result.current.refresh());
    expect(result.current.status).toBe('ready');
    expect(result.current.detail).toBe(before);

    await act(async () => pending.resolve({ data: withPrice(250) }));
    expect(result.current.status).toBe('ready');
    expect(result.current.detail.row.price).toBe(250);
  });

  it('keeps the old detail, and no error, when the silent read fails', async () => {
    publicacionesMlAPI.detail.mockResolvedValueOnce({ data: withPrice(100) });
    const { result } = renderHook(() => usePublicationDetail('MLA1', { canSeeMargin: false }));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    publicacionesMlAPI.detail.mockRejectedValueOnce(new Error('boom'));
    await act(async () => result.current.refresh());
    expect(result.current.status).toBe('ready');
    expect(result.current.error).toBeNull();
    expect(result.current.detail.row.price).toBe(100);
  });

  it('drops an answer that arrives after the selection moved on', async () => {
    publicacionesMlAPI.detail.mockResolvedValueOnce({ data: withPrice(100) });
    const { result, rerender } = renderHook(({ id }) => usePublicationDetail(id, { canSeeMargin: false }), { initialProps: { id: 'MLA1' } });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const late = deferred();
    publicacionesMlAPI.detail.mockReturnValueOnce(late.promise);
    act(() => result.current.refresh());

    const other = deferred();
    publicacionesMlAPI.detail.mockReturnValueOnce(other.promise);
    rerender({ id: 'MLA2' });
    expect(result.current.status).toBe('loading');

    await act(async () => late.resolve({ data: withPrice(999) }));
    expect(result.current.status).toBe('loading');
    await act(async () => other.resolve({ data: { ...withPrice(5), row: { ...DETAIL_RESPONSE.row, item_id: 'MLA2', price: 5 } } }));
    expect(result.current.detail.row.price).toBe(5);
  });

  it('keeps the newest answer when two refreshes overlap and the older one arrives last', async () => {
    publicacionesMlAPI.detail.mockResolvedValueOnce({ data: withPrice(100) });
    const { result } = renderHook(() => usePublicationDetail('MLA1', { canSeeMargin: false }));
    await waitFor(() => expect(result.current.status).toBe('ready'));
    const first = deferred();
    const second = deferred();
    publicacionesMlAPI.detail.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    act(() => result.current.refresh());
    act(() => result.current.refresh());
    await act(async () => second.resolve({ data: withPrice(300) }));
    await act(async () => first.resolve({ data: withPrice(200) }));
    expect(result.current.detail.row.price).toBe(300);
  });
});
