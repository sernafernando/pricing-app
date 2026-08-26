import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import {
  COLUMN_SIZING_STORAGE_KEYS,
  loadColumnSizing,
  saveColumnSizing,
  useColumnSizing,
} from './useColumnSizing';

// The non-negotiable constraint (PR4, ml-bot-panel-operador): renaming any
// of these four keys silently resets every operator's saved column widths
// on next load, with no error. Pin the literal strings so a future rename
// fails loudly here instead of being discovered by an operator.
describe('COLUMN_SIZING_STORAGE_KEYS — frozen literals', () => {
  it('preserves the exact four localStorage key strings', () => {
    expect(COLUMN_SIZING_STORAGE_KEYS.preguntas).toBe('mlq:colsizing:preguntas');
    expect(COLUMN_SIZING_STORAGE_KEYS.historial).toBe('mlq:colsizing:historial');
    expect(COLUMN_SIZING_STORAGE_KEYS.mensajes).toBe('mlq:colsizing:mensajes');
    expect(COLUMN_SIZING_STORAGE_KEYS.pendientes).toBe('mlq:colsizing:pendientes');
  });
});

describe('useColumnSizing — resize persistence round-trip', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('initializes from localStorage for the given key', () => {
    saveColumnSizing({ pregunta: 250 }, COLUMN_SIZING_STORAGE_KEYS.preguntas);
    const { result } = renderHook(() => useColumnSizing(COLUMN_SIZING_STORAGE_KEYS.preguntas));
    expect(result.current.columnSizing).toEqual({ pregunta: 250 });
  });

  it('persists a size change to the given key after the debounce, and only that key', () => {
    const { result } = renderHook(() => useColumnSizing(COLUMN_SIZING_STORAGE_KEYS.mensajes));

    act(() => {
      result.current.onColumnSizingChange({ mensaje: 400 });
    });
    expect(result.current.columnSizing).toEqual({ mensaje: 400 });
    // Not yet persisted — debounced.
    expect(loadColumnSizing(COLUMN_SIZING_STORAGE_KEYS.mensajes)).toEqual({});

    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(loadColumnSizing(COLUMN_SIZING_STORAGE_KEYS.mensajes)).toEqual({ mensaje: 400 });
    // Sibling tables' keys are untouched.
    expect(loadColumnSizing(COLUMN_SIZING_STORAGE_KEYS.preguntas)).toEqual({});
    expect(loadColumnSizing(COLUMN_SIZING_STORAGE_KEYS.pendientes)).toEqual({});
  });

  it('accepts a functional updater, matching TanStack onColumnSizingChange contract', () => {
    const { result } = renderHook(() => useColumnSizing(COLUMN_SIZING_STORAGE_KEYS.pendientes));

    act(() => {
      result.current.onColumnSizingChange((prev) => ({ ...prev, packComprador: 300 }));
    });
    expect(result.current.columnSizing).toEqual({ packComprador: 300 });
  });

  it('reset clears in-memory state and the persisted key', () => {
    saveColumnSizing({ fecha: 200 }, COLUMN_SIZING_STORAGE_KEYS.historial);
    const { result } = renderHook(() => useColumnSizing(COLUMN_SIZING_STORAGE_KEYS.historial));
    expect(result.current.hasCustom).toBe(true);

    act(() => {
      result.current.reset();
    });
    expect(result.current.columnSizing).toEqual({});
    expect(result.current.hasCustom).toBe(false);
    expect(loadColumnSizing(COLUMN_SIZING_STORAGE_KEYS.historial)).toEqual({});
  });

  it('hasCustom is false with no persisted sizing and true once a size is set', () => {
    const { result } = renderHook(() => useColumnSizing(COLUMN_SIZING_STORAGE_KEYS.preguntas));
    expect(result.current.hasCustom).toBe(false);

    act(() => {
      result.current.onColumnSizingChange({ pregunta: 300 });
    });
    expect(result.current.hasCustom).toBe(true);
  });
});
