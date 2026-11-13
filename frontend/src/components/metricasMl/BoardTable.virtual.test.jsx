/**
 * Métricas ML's "Todos" (filas-sin-limite S3): past `virtualizeFrom` rows the board renders only the rows in view,
 * with the same virtualization as Publicaciones ML's TableShell (`kit/useVirtualRows`). With `scrollerRef` the card
 * owns the scroll; without it (these unit mounts) the page itself scrolls.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import BoardTable from './BoardTable';
import { buildBoardColumns } from './metricasMlColumns';
import { nodeId } from '../../utils/metricasMlLevels';

// jsdom lays nothing out, so the virtualizer is told which rows the page shows: the first `view.last + 1`.
const view = vi.hoisted(() => ({ last: 19, options: null }));
vi.mock('@tanstack/react-virtual', async (importOriginal) => ({
  ...(await importOriginal()),
  useVirtualizer: (options) => {
    view.options = options;
    const { count, getItemKey } = options;
    const items = Array.from({ length: Math.min(count, view.last + 1) }, (_, index) => ({
      index,
      key: getItemKey(index),
      start: index * 56,
      end: (index + 1) * 56,
    }));
    return { getVirtualItems: () => items, getTotalSize: () => count * 56, measureElement: () => {}, options };
  },
}));

afterEach(() => {
  view.last = 19;
  view.options = null;
});

const base = {
  units: 1, units_24h: 0, units_3d: 0, units_7d: 0, units_15d: 0, units_30d: 1, gross: 200, total_gauss: 30,
  markup_pct: 30, series_units_90d: [], series_markup_90d: [], alerts: [],
};
const rowsOf = (n) =>
  Array.from({ length: n }, (_, i) => ({ ...base, key: String(i + 1), product_item_id: i + 1, title: `Producto ${i + 1}` }));

function renderBoard(rows, props = {}) {
  return render(
    <BoardTable
      rows={rows}
      columns={buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product' })}
      groupBy="product"
      canSeeMargin
      expanded={new Set()}
      subRows={{}}
      onToggleExpand={() => {}}
      sort="gross"
      sortDesc
      onSort={() => {}}
      now={new Date('2026-09-30T18:00:00Z')}
      {...props}
    />,
  );
}

describe('BoardTable virtualization', () => {
  it('past virtualizeFrom rows only the rows in view are in the DOM, scrolled by the page (window) without scrollerRef', () => {
    renderBoard(rowsOf(300), { virtualizeFrom: 100 });
    expect(screen.getByText('Producto 20')).toBeInTheDocument();
    expect(screen.queryByText('Producto 21')).not.toBeInTheDocument();
    expect(view.options.getScrollElement()).toBe(window);
  });

  it('with scrollerRef, virtualization scrolls that element (TableShell model)', () => {
    const scrollerRef = { current: document.createElement('div') };
    renderBoard(rowsOf(300), { virtualizeFrom: 100, scrollerRef });
    expect(view.options.getScrollElement()).toBe(scrollerRef.current);
  });

  it('up to virtualizeFrom rows, or without it, every row renders as before', () => {
    renderBoard(rowsOf(100), { virtualizeFrom: 100 });
    expect(screen.getByText('Producto 100')).toBeInTheDocument();
  });

  it('an open row keeps its publications under it, in its own measured block', () => {
    const id = nodeId(['1']);
    renderBoard(rowsOf(300), {
      virtualizeFrom: 100,
      expanded: new Set([id]),
      subRows: { [id]: { rows: [{ ...base, key: 'MLA9', mla: 'MLA9', title: 'Publicación abierta' }] } },
    });
    const block = screen.getByText('Producto 1').closest('tbody');
    expect(block).toHaveAttribute('data-index', '0');
    expect(block).toHaveTextContent('Publicación abierta');
  });

  it('calls onEndReached when the last rows come into view, once per rows', () => {
    const onEndReached = vi.fn();
    view.last = 299;
    const rows = rowsOf(300);
    const { rerender } = renderBoard(rows, { virtualizeFrom: 100, onEndReached });
    expect(onEndReached).toHaveBeenCalledTimes(1);
    rerender(
      <BoardTable
        rows={rows}
        columns={buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product' })}
        groupBy="product"
        canSeeMargin
        expanded={new Set()}
        subRows={{}}
        onToggleExpand={() => {}}
        sort="gross"
        sortDesc
        onSort={() => {}}
        virtualizeFrom={100}
        onEndReached={onEndReached}
      />,
    );
    expect(onEndReached).toHaveBeenCalledTimes(1);
  });
});
