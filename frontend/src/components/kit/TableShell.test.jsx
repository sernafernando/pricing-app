/**
 * TableShell (publicaciones-ml-vista P10b.T2). Structure and behaviour only:
 * the unit project runs with `css: false`, so "sticky inside its own
 * scroller" is proved in real Chromium by `src/test/visual/kit.visual.test.jsx`.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TableShell from './TableShell';

const COLUMNS = [
  { key: 'title', header: 'Publicación', width: 320, render: (r) => r.title },
  { key: 'price', header: 'Precio', width: '12%', sortable: true, render: (r) => r.price },
  { key: 'stock', header: 'Stock', sortable: true, render: (r) => r.stock },
];
const ROWS = [
  { id: 'A', title: 'Router AX', price: 100, stock: 3 },
  { id: 'B', title: 'Switch 8p', price: 50, stock: 0 },
];

const renderShell = (props = {}) =>
  render(<TableShell columns={COLUMNS} rows={ROWS} getRowKey={(r) => r.id} ariaLabel="Publicaciones" {...props} />);

describe('structure', () => {
  it('renders its own scroller wrapping a labelled table', () => {
    const { container } = renderShell();
    const scroller = container.querySelector('[data-table-shell-scroller]');
    expect(scroller).not.toBeNull();
    expect(within(scroller).getByRole('table', { name: 'Publicaciones' })).toBeInTheDocument();
  });

  it('renders one th per column and one row per item', () => {
    renderShell();
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Publicación',
      'Precio',
      'Stock',
    ]);
    expect(screen.getByText('Router AX')).toBeInTheDocument();
    expect(screen.getByText('Switch 8p')).toBeInTheDocument();
  });

  it('marks the first column of header and body as the pinned one', () => {
    const { container } = renderShell();
    expect(container.querySelector('thead th')).toHaveAttribute('data-pinned');
    expect(container.querySelector('tbody tr td')).toHaveAttribute('data-pinned');
    expect(container.querySelectorAll('[data-pinned]')).toHaveLength(1 + ROWS.length);
  });

  it('emits a colgroup with the declared widths (numbers as px, strings verbatim)', () => {
    const { container } = renderShell();
    const cols = [...container.querySelectorAll('colgroup col')];
    expect(cols).toHaveLength(3);
    expect(cols.map((c) => c.style.width)).toEqual(['320px', '12%', '']);
  });

  it('shows the empty message and no body rows without data', () => {
    renderShell({ rows: [], emptyMessage: 'Sin publicaciones' });
    expect(screen.getByText('Sin publicaciones')).toBeInTheDocument();
  });

  it('passes the offset to the scroller as --table-shell-offset', () => {
    const { container } = renderShell({ offset: '260px' });
    expect(container.querySelector('[data-table-shell-scroller]').style.getPropertyValue('--table-shell-offset')).toBe(
      '260px',
    );
  });
});

describe('column groups', () => {
  const GROUPED = [
    { key: 'title', header: 'Publicación', group: 'Datos', render: (r) => r.title },
    { key: 'price', header: 'Precio', group: 'Datos', render: (r) => r.price },
    { key: 'stock', header: 'Stock', group: 'Inventario', render: (r) => r.stock },
    { key: 'x', header: 'Extra', render: () => '' },
  ];

  it('adds a group row spanning consecutive columns of the same group', () => {
    const { container } = renderShell({ columns: GROUPED });
    const groupRow = container.querySelectorAll('thead tr')[0];
    const cells = [...groupRow.querySelectorAll('th')];
    expect(cells.map((c) => [c.textContent, c.colSpan])).toEqual([
      ['Datos', 2],
      ['Inventario', 1],
      ['', 1],
    ]);
    expect(container.querySelectorAll('thead tr')).toHaveLength(2);
  });

  it('has a single header row when no column declares a group', () => {
    const { container } = renderShell();
    expect(container.querySelectorAll('thead tr')).toHaveLength(1);
  });
});

describe('sorting', () => {
  it('renders sort buttons only for sortable columns', () => {
    renderShell();
    expect(screen.queryByRole('button', { name: /Publicación/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Precio/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Stock/ })).toBeInTheDocument();
  });

  it('calls onSort with the column key', async () => {
    const onSort = vi.fn();
    renderShell({ onSort });
    await userEvent.click(screen.getByRole('button', { name: /Precio/ }));
    expect(onSort).toHaveBeenCalledWith('price');
  });

  it('exposes aria-sort on the active column only', () => {
    renderShell({ sort: { key: 'price', dir: 'desc' } });
    const headers = screen.getAllByRole('columnheader');
    expect(headers[1]).toHaveAttribute('aria-sort', 'descending');
    expect(headers[2]).not.toHaveAttribute('aria-sort');
    expect(headers[0]).not.toHaveAttribute('aria-sort');
  });

  it('maps asc to ascending', () => {
    renderShell({ sort: { key: 'stock', dir: 'asc' } });
    expect(screen.getAllByRole('columnheader')[2]).toHaveAttribute('aria-sort', 'ascending');
  });
});

describe('tree rows', () => {
  const TREE = [
    { id: 'g', title: 'Grupo', depth: 0 },
    { id: 'c', title: 'Hijo', depth: 2 },
  ];

  it('sets --indent from getRowDepth and defaults to 0', () => {
    renderShell({ rows: TREE, getRowDepth: (r) => r.depth });
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0].style.getPropertyValue('--indent')).toBe('0');
    expect(rows[1].style.getPropertyValue('--indent')).toBe('2');
  });

  it('defaults --indent to 0 without getRowDepth', () => {
    renderShell();
    expect(screen.getAllByRole('row')[1].style.getPropertyValue('--indent')).toBe('0');
  });
});

describe('renderSubRows', () => {
  it('renders the returned rows right after their parent row', () => {
    const renderSubRows = (row) =>
      row.id === 'A' ? (
        <tr data-testid="sub">
          <td colSpan={3}>variación de A</td>
        </tr>
      ) : null;
    const { container } = renderShell({ renderSubRows });
    const trs = [...container.querySelectorAll('tbody tr')];
    expect(trs).toHaveLength(3);
    expect(trs[1]).toHaveAttribute('data-testid', 'sub');
    expect(trs[2]).toHaveTextContent('Switch 8p');
  });
});

describe('row interaction', () => {
  it('calls onRowClick with the row and flags the selected one with aria-current', async () => {
    const onRowClick = vi.fn();
    renderShell({ onRowClick, selectedKey: 'B' });
    const rows = screen.getAllByRole('row');
    expect(rows[2]).toHaveAttribute('aria-current', 'true');
    expect(rows[2]).toHaveAttribute('data-selected');
    expect(rows[1]).not.toHaveAttribute('aria-current');
    await userEvent.click(screen.getByText('Router AX'));
    expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);
  });

  it('never uses aria-selected (invalid on a plain table row)', () => {
    const { container } = renderShell({ onRowClick: vi.fn(), selectedKey: 'B' });
    expect(container.querySelector('[aria-selected]')).toBeNull();
  });

  it('makes clickable rows keyboard reachable and activates them with Enter and Space', async () => {
    const onRowClick = vi.fn();
    renderShell({ onRowClick });
    const row = screen.getAllByRole('row')[1];
    expect(row).toHaveAttribute('tabindex', '0');
    row.focus();
    await userEvent.keyboard('{Enter}');
    expect(onRowClick).toHaveBeenLastCalledWith(ROWS[0]);
    await userEvent.keyboard(' ');
    expect(onRowClick).toHaveBeenCalledTimes(2);
  });

  it('does not hijack keys typed inside a control within the row', async () => {
    const onRowClick = vi.fn();
    const columns = [{ key: 'n', header: 'Nota', render: () => <input aria-label="nota" /> }];
    renderShell({ columns, onRowClick });
    await userEvent.click(screen.getAllByLabelText('nota')[0]);
    onRowClick.mockClear();
    await userEvent.keyboard(' {Enter}');
    expect(onRowClick).not.toHaveBeenCalled();
  });

  it('does not open the row when a click lands on a control inside a cell', async () => {
    const onRowClick = vi.fn();
    const inner = vi.fn();
    const columns = [
      { key: 'a', header: 'A', render: (r) => r.title },
      {
        key: 'b',
        header: 'B',
        render: () => (
          <>
            <button type="button" onClick={inner}>
              copiar
            </button>
            <a href="#x">ver</a>
          </>
        ),
      },
    ];
    renderShell({ columns, onRowClick });
    await userEvent.click(screen.getAllByRole('button', { name: 'copiar' })[0]);
    await userEvent.click(screen.getAllByRole('link', { name: 'ver' })[0]);
    expect(inner).toHaveBeenCalledTimes(1);
    expect(onRowClick).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText('Router AX'));
    expect(onRowClick).toHaveBeenCalledTimes(1);
  });

  it('does not make rows clickable or focusable without onRowClick', () => {
    renderShell();
    const row = screen.getAllByRole('row')[1];
    expect(row).not.toHaveAttribute('data-clickable');
    expect(row).not.toHaveAttribute('tabindex');
  });
});
