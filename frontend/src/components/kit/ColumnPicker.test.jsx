import { describe, it, expect, vi } from 'vitest';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useReactTable, getCoreRowModel } from '@tanstack/react-table';
import ColumnPicker from './ColumnPicker';

// dnd-kit's gestures do not run in jsdom (TicketsBoard.test.jsx): each DndContext's `onDragEnd` -- the very handler a
// pointer or keyboard drag ends in -- is captured by its `id` and called with dnd-kit's event shape.
const dragEnd = vi.hoisted(() => ({}));
vi.mock('@dnd-kit/core', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    DndContext: ({ id, onDragEnd, children }) => {
      dragEnd[id] = onDragEnd;
      return children;
    },
  };
});

const COLUMNS = [
  { id: 'locked', header: 'Locked', size: 10, enableHiding: false, cell: () => null },
  { id: 'a', header: 'A', size: 10, cell: () => null },
  { id: 'b', header: 'B', size: 10, cell: () => null },
];

function TestHarness(props) {
  const table = useReactTable({
    columns: COLUMNS,
    data: [],
    getCoreRowModel: getCoreRowModel(),
  });
  return <ColumnPicker table={table} {...props} />;
}

describe('ColumnPicker', () => {
  it('is closed by default and opens the popover on click', async () => {
    const user = userEvent.setup();
    render(<TestHarness />);

    // `role="group"`, not `role="menu"`: see the comment on the popover in
    // ColumnPicker.jsx -- a `menu` promises a `menuitemcheckbox` keyboard
    // contract these plain checkboxes do not implement.
    expect(screen.queryByRole('group', { name: /columnas visibles/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    expect(screen.getByRole('group', { name: /columnas visibles/i })).toBeInTheDocument();
  });

  it('closes on Escape and hands focus back to the trigger', async () => {
    const user = userEvent.setup();
    render(<TestHarness />);

    const trigger = screen.getByRole('button', { name: 'Columnas' });
    await user.click(trigger);
    expect(screen.getByRole('group', { name: /columnas visibles/i })).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('group', { name: /columnas visibles/i })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('lists only the hideable columns, never one with enableHiding: false', async () => {
    const user = userEvent.setup();
    render(<TestHarness />);

    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    expect(screen.queryByRole('checkbox', { name: 'Locked' })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'A' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'B' })).toBeInTheDocument();
  });

  it('toggles a column off and back on via its checkbox', async () => {
    const user = userEvent.setup();
    render(<TestHarness />);

    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    const checkboxA = screen.getByRole('checkbox', { name: 'A' });
    expect(checkboxA).toBeChecked();

    await user.click(checkboxA);
    expect(checkboxA).not.toBeChecked();

    await user.click(checkboxA);
    expect(checkboxA).toBeChecked();
  });

  it('takes its own label, so a second picker (Indicadores) sits beside Columnas with its own popover', async () => {
    const user = userEvent.setup();
    function Two() {
      const table = useReactTable({ columns: COLUMNS, data: [], getCoreRowModel: getCoreRowModel() });
      return (
        <>
          <ColumnPicker table={table} />
          <ColumnPicker table={table} label="Indicadores" groupLabel="Elegir indicadores visibles" />
        </>
      );
    }
    render(<Two />);
    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    await user.click(screen.getByRole('button', { name: 'Indicadores' }));
    const kpis = screen.getByRole('group', { name: 'Elegir indicadores visibles' });
    expect(screen.getByRole('button', { name: 'Indicadores' })).toHaveAttribute('aria-controls', kpis.id);
    expect(kpis.id).not.toBe(screen.getByRole('button', { name: 'Columnas' }).getAttribute('aria-controls'));
  });

  it('keeps its label and outline by default, and iconOnly shows just the icon, named by the label', () => {
    const { unmount } = render(<TestHarness />);
    const labelled = screen.getByRole('button', { name: 'Columnas' });
    expect(labelled).toHaveTextContent('Columnas');
    expect(labelled).toHaveClass('btn-tesla', 'outline', 'sm');
    unmount();
    render(<TestHarness iconOnly buttonClassName="btn-tesla sm quiet" />);
    const icon = screen.getByRole('button', { name: 'Columnas' });
    expect(icon).toHaveTextContent('');
    expect(icon).toHaveAttribute('title', 'Columnas');
    expect(icon).toHaveClass('btn-tesla', 'sm', 'quiet', 'icon-only');
    expect(icon).not.toHaveClass('outline');
  });
});

describe('ColumnPicker without onReorder (every other page): exactly as before', () => {
  it('has no drag handles and no Restablecer', async () => {
    const user = userEvent.setup();
    render(<TestHarness />);
    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    const group = screen.getByRole('group', { name: /columnas visibles/i });
    expect(within(group).getAllByRole('checkbox').map((box) => box.closest('label').textContent)).toEqual(['A', 'B']);
    expect(within(group).queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByText('Restablecer')).not.toBeInTheDocument();
  });
});

// Columns as the Publicaciones ML page hands them: a fixed first column, ungrouped ones, and groups (`meta.group`).
const GROUPED = [
  { id: 'titulo', header: 'Publicación', enableHiding: false, cell: () => null },
  { id: 'tipo', header: 'Tipo', cell: () => null },
  { id: 'u7', header: 'Ventas 7D', meta: { group: 'Ventas' }, cell: () => null },
  { id: 'u30', header: 'Ventas 30D', meta: { group: 'Ventas' }, cell: () => null },
  { id: 'erp', header: 'Stock ERP', meta: { group: 'Stock' }, cell: () => null },
  { id: 'full', header: 'Stock Full', meta: { group: 'Stock' }, cell: () => null },
];

function Reorderable(props) {
  const table = useReactTable({ columns: GROUPED, data: [], getCoreRowModel: getCoreRowModel() });
  return <ColumnPicker table={table} {...props} />;
}

describe('ColumnPicker with onReorder (pubml-columnas-presets S1)', () => {
  it('lists each group under its name with one handle for the group and one per column, the fixed column left out', async () => {
    const user = userEvent.setup();
    render(<Reorderable onReorder={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    expect(screen.getByRole('button', { name: 'Mover grupo Ventas' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mover grupo Stock' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mover Tipo' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mover Ventas 30D' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Mover Publicación' })).not.toBeInTheDocument();
    // The checkboxes keep their names: the visibility still toggles as before.
    expect(screen.getByRole('checkbox', { name: 'Ventas 7D' })).toBeChecked();
  });

  it('dropping a group on another moves the whole group', async () => {
    const user = userEvent.setup();
    const onReorder = vi.fn();
    render(<Reorderable onReorder={onReorder} />);
    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    act(() => dragEnd['column-blocks']({ active: { id: 'group:Stock' }, over: { id: 'col:tipo' } }));
    expect(onReorder).toHaveBeenCalledWith(['erp', 'full', 'tipo', 'u7', 'u30']);
  });

  it('a column moves only inside its group', async () => {
    const user = userEvent.setup();
    const onReorder = vi.fn();
    render(<Reorderable onReorder={onReorder} />);
    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    act(() => dragEnd['column-group-Ventas']({ active: { id: 'u30' }, over: { id: 'u7' } }));
    expect(onReorder).toHaveBeenCalledWith(['tipo', 'u30', 'u7', 'erp', 'full']);
    onReorder.mockClear();
    // Dropped on a column of another group (or nowhere): nothing moves.
    act(() => dragEnd['column-group-Ventas']({ active: { id: 'u30' }, over: { id: 'erp' } }));
    act(() => dragEnd['column-group-Ventas']({ active: { id: 'u30' }, over: null }));
    expect(onReorder).not.toHaveBeenCalled();
  });

  it('Restablecer calls onReset', async () => {
    const user = userEvent.setup();
    const onReset = vi.fn();
    render(<Reorderable onReorder={vi.fn()} onReset={onReset} />);
    await user.click(screen.getByRole('button', { name: 'Columnas' }));
    await user.click(screen.getByRole('button', { name: 'Restablecer' }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
