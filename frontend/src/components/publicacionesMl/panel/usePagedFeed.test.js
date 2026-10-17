/**
 * usePagedFeed: a second `loadMore` before the first page answers must not ask
 * for the same page again, whether or not a query (`tecnicos`) goes along. The
 * button is also disabled while loading, so this pins the hook's own guard:
 * two calls in the same tick, before any re-render.
 */
import { describe, it, expect, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { usePagedFeed } from './usePagedFeed';

const CURSOR = '2026-10-15T13:49:31.393877Z|123143';

function setup(query) {
  let resolveNext;
  const fetchPage = vi
    .fn()
    .mockResolvedValueOnce({ data: { entries: [{ id: 1 }], next_cursor: CURSOR } })
    .mockReturnValueOnce(new Promise((resolve) => (resolveNext = resolve)));
  const view = renderHook(() => usePagedFeed(fetchPage, 'MLA1402898289', 'entries', query));
  return { fetchPage, view, resolveNext: (data) => resolveNext({ data }) };
}

async function doubleLoadMore({ fetchPage, view, resolveNext }) {
  await waitFor(() => expect(view.result.current.status).toBe('ready'));
  act(() => {
    view.result.current.loadMore();
    view.result.current.loadMore();
  });
  expect(fetchPage).toHaveBeenCalledTimes(2);
  await act(async () => resolveNext({ entries: [{ id: 2 }], next_cursor: null }));
  expect(view.result.current.items.map((item) => item.id)).toEqual([1, 2]);
  expect(fetchPage).toHaveBeenCalledTimes(2);
}

describe('loadMore twice before the next page answers', () => {
  it('asks for the next page once', async () => {
    const feed = setup(undefined);
    await doubleLoadMore(feed);
    expect(feed.fetchPage).toHaveBeenLastCalledWith('MLA1402898289', { cursor: CURSOR });
  });

  it('with tecnicos on, asks once, and the request carries tecnicos', async () => {
    const feed = setup({ tecnicos: true });
    await doubleLoadMore(feed);
    expect(feed.fetchPage).toHaveBeenNthCalledWith(1, 'MLA1402898289', { tecnicos: true });
    expect(feed.fetchPage).toHaveBeenLastCalledWith('MLA1402898289', { tecnicos: true, cursor: CURSOR });
  });
});
