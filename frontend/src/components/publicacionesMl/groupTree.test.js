/** The flat rows of the Agrupado tree (publicaciones-ml-vista P12a): what `TableShell` is given. */
import { describe, it, expect } from 'vitest';
import { branchKey, flattenTree } from './groupTree';

const node = (key, over = {}) => ({ kind: 'marca', key, label: key, count: 5, leaf: false, params: {}, ...over });
const ready = (rows, total = rows.length, over = {}) => ({ status: 'ready', rows, total, error: null, ...over });

describe('branchKey', () => {
  it('joins the keys as they came', () => {
    expect(branchKey([])).toBe('');
    expect(branchKey(['A%2CB', 'CAT'])).toBe('A%2CB,CAT');
  });
});

describe('flattenTree', () => {
  it('lists the roots at depth 0 and nothing under a collapsed node', () => {
    const rows = flattenTree({ branches: { '': ready([node('A'), node('B')]) }, expanded: new Set() });
    expect(rows.map((r) => [r.type, r.id, r.depth])).toEqual([
      ['node', 'n:A', 0],
      ['node', 'n:B', 0],
    ]);
  });

  it('puts the children of an expanded node right under it, one level in', () => {
    const rows = flattenTree({
      branches: { '': ready([node('A'), node('B')]), A: ready([node('X', { kind: 'categoria' })]) },
      expanded: new Set(['A']),
    });
    expect(rows.map((r) => [r.id, r.depth])).toEqual([
      ['n:A', 0],
      ['n:A,X', 1],
      ['n:B', 0],
    ]);
    expect(rows[0].expanded).toBe(true);
    expect(rows[1].path).toEqual(['A', 'X']);
  });

  it('lists the publications of a leaf by their MLA id, under the node', () => {
    const rows = flattenTree({
      branches: { '': ready([node('P', { leaf: true })]), P: ready([{ item_id: 'MLA1' }, { item_id: 'MLA2' }], 2, { leaf: true }) },
      expanded: new Set(['P']),
    });
    expect(rows.map((r) => [r.type, r.id, r.depth])).toEqual([
      ['node', 'n:P', 0],
      ['item', 'MLA1', 1],
      ['item', 'MLA2', 1],
    ]);
  });

  it('adds "Ver más" while the node has more than it loaded, with what is left', () => {
    const rows = flattenTree({ branches: { '': ready([node('A'), node('B')], 250) }, expanded: new Set() });
    expect(rows.at(-1)).toMatchObject({ type: 'more', id: 'm:', remaining: 248, loading: false, depth: 0 });
  });

  it('shows loading, error and empty under the node that asked', () => {
    const open = (child) => flattenTree({ branches: { '': ready([node('A')]), A: child }, expanded: new Set(['A']) }).at(-1);
    expect(open({ status: 'loading', rows: [], total: 0 })).toMatchObject({ type: 'state', state: 'loading', depth: 1 });
    expect(open({ status: 'error', rows: [], total: 0, error: new Error('x') })).toMatchObject({ type: 'state', state: 'error', pathKey: 'A' });
    expect(open(ready([]))).toMatchObject({ type: 'state', state: 'empty' });
  });

  it('keeps what loaded when a later page fails, and the error row retries', () => {
    const rows = flattenTree({
      branches: { '': { status: 'error', rows: [node('A')], total: 300, error: new Error('x') } },
      expanded: new Set(),
    });
    expect(rows.map((r) => r.type)).toEqual(['node', 'state']);
  });

  it('shows "Ver más" as loading while the next page comes', () => {
    const rows = flattenTree({ branches: { '': { status: 'more', rows: [node('A')], total: 300, error: null } }, expanded: new Set() });
    expect(rows.at(-1)).toMatchObject({ type: 'more', loading: true });
  });

  it('shows nothing for a root that is empty (the table says so)', () => {
    expect(flattenTree({ branches: { '': ready([]) }, expanded: new Set() })).toEqual([]);
  });
});
