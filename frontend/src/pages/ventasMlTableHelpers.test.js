import { describe, it, expect, beforeEach } from 'vitest';
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

import { pageWindow, loadPageSize, savePageSize, PAGE_SIZE_OPTIONS, DEFAULT_PAGE_SIZE } from './ventasMlTableHelpers';

describe('pageWindow', () => {
  it('lists every page when there are few', () => {
    expect(pageWindow(1, 4)).toEqual([1, 2, 3, 4]);
  });

  it('collapses the far ends into ellipses around the current page', () => {
    expect(pageWindow(10, 20)).toEqual([1, 'gap-start', 9, 10, 11, 'gap-end', 20]);
  });

  it('does not leave a gap for a single skipped page', () => {
    expect(pageWindow(3, 10)).toEqual([1, 2, 3, 4, 'gap-end', 10]);
  });

  it('keeps first and last reachable at the edges', () => {
    expect(pageWindow(1, 20)).toEqual([1, 2, 'gap-end', 20]);
    expect(pageWindow(20, 20)).toEqual([1, 'gap-start', 19, 20]);
  });

  it('returns a single page for an empty or one-page set', () => {
    expect(pageWindow(1, 1)).toEqual([1]);
    expect(pageWindow(1, 0)).toEqual([1]);
  });
});

describe('page size persistence', () => {
  beforeEach(() => localStorage.clear());

  it('defaults to 50 and only offers sizes the endpoint accepts (max 200)', () => {
    expect(DEFAULT_PAGE_SIZE).toBe(50);
    expect(PAGE_SIZE_OPTIONS).toEqual([25, 50, 100, 200]);
    expect(loadPageSize()).toBe(50);
  });

  it('round-trips a valid size', () => {
    savePageSize(100);
    expect(loadPageSize()).toBe(100);
  });

  it('ignores a stale or foreign value', () => {
    localStorage.setItem('ventasml:pagesize', '999');
    expect(loadPageSize()).toBe(50);
    localStorage.setItem('ventasml:pagesize', 'abc');
    expect(loadPageSize()).toBe(50);
  });
});
