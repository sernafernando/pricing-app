import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useResizableColumns } from './useResizableColumns';

const STORAGE_KEY = 'mlbot:colwidths:test';

const COLUMNS = [
  { id: 'pregunta', label: 'Pregunta', resizable: true, min: 100, max: 400, defaultWidth: 200 },
  { id: 'item', label: 'Item', resizable: true, min: 80, max: 300, defaultWidth: 150 },
  { id: 'estado', label: 'Estado', resizable: false, min: 60, max: 60, defaultWidth: 60 },
];

function renderColumns(storageKey = STORAGE_KEY, columns = COLUMNS) {
  return renderHook(() => useResizableColumns({ storageKey, columns }));
}

function pressKey(getHandleProps, id, key, opts = {}) {
  const props = getHandleProps(id);
  const event = { key, shiftKey: false, preventDefault: () => {}, ...opts };
  act(() => {
    props.onKeyDown(event);
  });
}

describe('useResizableColumns', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useRealTimers();
  });

  it('init with no storage: colWidth undefined for all cols, isResized false', () => {
    const { result } = renderColumns();
    for (const col of COLUMNS) {
      expect(result.current.colWidth(col.id)).toBeUndefined();
      expect(result.current.isResized(col.id)).toBe(false);
    }
  });

  it('ArrowRight/ArrowLeft step ±16px from defaultWidth baseline', () => {
    const { result } = renderColumns();
    pressKey(result.current.getHandleProps, 'pregunta', 'ArrowRight');
    expect(result.current.colWidth('pregunta')).toBe(216);

    pressKey(result.current.getHandleProps, 'pregunta', 'ArrowLeft');
    pressKey(result.current.getHandleProps, 'pregunta', 'ArrowLeft');
    expect(result.current.colWidth('pregunta')).toBe(184);
  });

  it('Shift+Arrow steps ×4 (±64px)', () => {
    const { result } = renderColumns();
    pressKey(result.current.getHandleProps, 'pregunta', 'ArrowRight', { shiftKey: true });
    expect(result.current.colWidth('pregunta')).toBe(264);
  });

  it('Home/End jump to min/max', () => {
    const { result } = renderColumns();
    pressKey(result.current.getHandleProps, 'pregunta', 'End');
    expect(result.current.colWidth('pregunta')).toBe(400);

    pressKey(result.current.getHandleProps, 'pregunta', 'Home');
    expect(result.current.colWidth('pregunta')).toBe(100);
  });

  it('clamps keyboard resize to [min, max]', () => {
    const { result } = renderColumns();
    // Push far past max via many ArrowRight presses
    for (let i = 0; i < 20; i++) {
      pressKey(result.current.getHandleProps, 'pregunta', 'ArrowRight');
    }
    expect(result.current.colWidth('pregunta')).toBe(400);

    for (let i = 0; i < 40; i++) {
      pressKey(result.current.getHandleProps, 'pregunta', 'ArrowLeft');
    }
    expect(result.current.colWidth('pregunta')).toBe(100);
  });

  it('persistence round-trip: resize via keyboard -> unmount -> remount same storageKey -> width restored', () => {
    vi.useFakeTimers();
    const { result, unmount } = renderColumns();
    pressKey(result.current.getHandleProps, 'pregunta', 'End');
    // debounced write (300ms)
    act(() => {
      vi.advanceTimersByTime(400);
    });
    unmount();
    vi.useRealTimers();

    const { result: result2 } = renderColumns();
    expect(result2.current.colWidth('pregunta')).toBe(400);
    expect(result2.current.isResized('pregunta')).toBe(true);
  });

  it('resetWidths clears in-memory overrides AND removes localStorage key; subsequent remount starts clean', () => {
    vi.useFakeTimers();
    const { result, unmount } = renderColumns();
    pressKey(result.current.getHandleProps, 'pregunta', 'End');
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(localStorage.getItem(STORAGE_KEY)).not.toBeNull();

    act(() => {
      result.current.resetWidths();
    });
    expect(result.current.colWidth('pregunta')).toBeUndefined();
    expect(result.current.isResized('pregunta')).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();

    unmount();
    vi.useRealTimers();
    const { result: result2 } = renderColumns();
    expect(result2.current.colWidth('pregunta')).toBeUndefined();
  });

  it('corrupt localStorage value (invalid JSON) falls back to defaults, does not throw', () => {
    localStorage.setItem(STORAGE_KEY, 'not json');
    expect(() => renderColumns()).not.toThrow();
    const { result } = renderColumns();
    expect(result.current.colWidth('pregunta')).toBeUndefined();
    expect(result.current.isResized('pregunta')).toBe(false);
  });

  it('out-of-range persisted value (below min / above max) is re-clamped on load', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ pregunta: 9999, item: -50 }));
    const { result } = renderColumns();
    expect(result.current.colWidth('pregunta')).toBe(400);
    expect(result.current.colWidth('item')).toBe(80);
  });

  it('localStorage disabled/throwing (setItem throws) -> live in-memory resize still works, no throw', () => {
    const originalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error('QuotaExceededError');
    };
    vi.useFakeTimers();
    try {
      const { result } = renderColumns();
      expect(() => {
        pressKey(result.current.getHandleProps, 'pregunta', 'ArrowRight');
        act(() => {
          vi.advanceTimersByTime(400);
        });
      }).not.toThrow();
      expect(result.current.colWidth('pregunta')).toBe(216);
    } finally {
      Storage.prototype.setItem = originalSetItem;
      vi.useRealTimers();
    }
  });

  it('getHandleProps returns role=separator, aria-orientation=vertical, aria-label with column label, tabIndex=0', () => {
    const { result } = renderColumns();
    const props = result.current.getHandleProps('pregunta');
    expect(props.role).toBe('separator');
    expect(props['aria-orientation']).toBe('vertical');
    expect(props['aria-label']).toContain('Pregunta');
    expect(props.tabIndex).toBe(0);
  });
});
