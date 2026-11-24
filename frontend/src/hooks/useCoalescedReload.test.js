/**
 * useCoalescedReload (handoffs/drain-diagnostico.md): a burst of SSE events reloads the label list at most once per
 * interval, never twice at the same time, and not at all while the page is hidden.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useCoalescedReload, RELOAD_MIN_INTERVAL_MS } from './useCoalescedReload';

let hidden = false;

function setHidden(value) {
  hidden = value;
  document.dispatchEvent(new Event('visibilitychange'));
}

async function advance(ms) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  hidden = false;
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('useCoalescedReload', () => {
  it('reloads at once on the first event', async () => {
    const reload = vi.fn().mockResolvedValue();
    const { result } = renderHook(() => useCoalescedReload(reload));

    act(() => result.current());
    await advance(0);

    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('turns a burst of events into one more reload at the end of the interval', async () => {
    const reload = vi.fn().mockResolvedValue();
    const { result } = renderHook(() => useCoalescedReload(reload));

    act(() => result.current());
    await advance(0);
    for (let i = 0; i < 20; i += 1) {
      act(() => result.current());
      await advance(100);
    }
    expect(reload).toHaveBeenCalledTimes(1);

    await advance(RELOAD_MIN_INTERVAL_MS);
    expect(reload).toHaveBeenCalledTimes(2);
    await advance(RELOAD_MIN_INTERVAL_MS * 3);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it('never runs two reloads at the same time: an event during one runs one more after it', async () => {
    let terminar;
    const reload = vi.fn(() => new Promise((resolve) => (terminar = resolve)));
    const { result } = renderHook(() => useCoalescedReload(reload));

    act(() => result.current());
    await advance(0);
    act(() => result.current());
    act(() => result.current());
    await advance(RELOAD_MIN_INTERVAL_MS * 2);
    expect(reload).toHaveBeenCalledTimes(1);

    await act(async () => terminar());
    await advance(0);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it('reloads nothing while the page is hidden, and once when it is visible again', async () => {
    const reload = vi.fn().mockResolvedValue();
    const { result } = renderHook(() => useCoalescedReload(reload));

    setHidden(true);
    for (let i = 0; i < 5; i += 1) act(() => result.current());
    await advance(RELOAD_MIN_INTERVAL_MS * 4);
    expect(reload).not.toHaveBeenCalled();

    act(() => setHidden(false));
    await advance(0);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('a page shown again without missed events does not reload', async () => {
    const reload = vi.fn().mockResolvedValue();
    renderHook(() => useCoalescedReload(reload));

    act(() => setHidden(true));
    act(() => setHidden(false));
    await advance(RELOAD_MIN_INTERVAL_MS);

    expect(reload).not.toHaveBeenCalled();
  });

  it('calls the latest reload, and nothing after unmounting', async () => {
    const primero = vi.fn().mockResolvedValue();
    const segundo = vi.fn().mockResolvedValue();
    const { result, rerender, unmount } = renderHook(({ fn }) => useCoalescedReload(fn), {
      initialProps: { fn: primero },
    });

    rerender({ fn: segundo });
    act(() => result.current());
    await advance(0);
    expect([primero.mock.calls.length, segundo.mock.calls.length]).toEqual([0, 1]);

    act(() => result.current());
    unmount();
    await advance(RELOAD_MIN_INTERVAL_MS * 2);
    expect(segundo).toHaveBeenCalledTimes(1);
  });

  it('does not reload after unmounting, even with an event that arrived during the last reload', async () => {
    let terminar;
    const reload = vi.fn(() => new Promise((resolve) => (terminar = resolve)));
    const { result, unmount } = renderHook(() => useCoalescedReload(reload));

    act(() => result.current());
    await advance(0);
    act(() => result.current());
    unmount();
    await act(async () => terminar());
    await advance(RELOAD_MIN_INTERVAL_MS * 2);

    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('keeps an event that arrived during a reload that then fails', async () => {
    let fallar;
    const reload = vi
      .fn()
      .mockImplementationOnce(() => new Promise((_, reject) => (fallar = reject)))
      .mockResolvedValue();
    const { result } = renderHook(() => useCoalescedReload(reload));

    act(() => result.current());
    await advance(0);
    act(() => result.current());
    await act(async () => fallar(new Error('red caída')));
    await advance(RELOAD_MIN_INTERVAL_MS);

    expect(reload).toHaveBeenCalledTimes(2);
  });
});
