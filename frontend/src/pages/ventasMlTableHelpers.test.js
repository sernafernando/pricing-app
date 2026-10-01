import { describe, it, expect } from 'vitest';
import { resizeColumns, COLUMN_SIZING_STORAGE_KEY } from './ventasMlTableHelpers';

const ORDER = ['a', 'b', 'c'];
const WIDTHS = { a: 100, b: 200, c: 300 };
const MINS = { a: 50, b: 80, c: 60 };

describe('COLUMN_SIZING_STORAGE_KEY', () => {
  it('is frozen: renaming it silently resets every operator widths', () => {
    expect(COLUMN_SIZING_STORAGE_KEY).toBe('ventasml:colsizing');
  });
});

describe('resizeColumns', () => {
  it('moves the border: the column grows and its right neighbour shrinks by the same amount', () => {
    const next = resizeColumns(WIDTHS, ORDER, 'a', 30, MINS);
    expect(next).toEqual({ a: 130, b: 170, c: 300 });
  });

  it('keeps the total constant so nothing else on the row moves', () => {
    const next = resizeColumns(WIDTHS, ORDER, 'b', -40, MINS);
    expect(next.a + next.b + next.c).toBe(600);
  });

  it('never takes the dragged column below its minimum', () => {
    const next = resizeColumns(WIDTHS, ORDER, 'a', -500, MINS);
    expect(next.a).toBe(50);
    expect(next.b).toBe(250);
  });

  it('never takes the neighbour below its minimum (the overlap bug)', () => {
    const next = resizeColumns(WIDTHS, ORDER, 'a', 500, MINS);
    expect(next.b).toBe(80);
    expect(next.a).toBe(220);
  });

  it('is a no-op for the last visible column (its right edge is the table edge)', () => {
    expect(resizeColumns(WIDTHS, ORDER, 'c', 20, MINS)).toEqual(WIDTHS);
  });

  it('is a no-op for an unknown column id', () => {
    expect(resizeColumns(WIDTHS, ORDER, 'zzz', 20, MINS)).toEqual(WIDTHS);
  });
});
