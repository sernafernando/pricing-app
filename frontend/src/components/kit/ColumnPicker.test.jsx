import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useReactTable, getCoreRowModel } from '@tanstack/react-table';
import ColumnPicker from './ColumnPicker';

const COLUMNS = [
  { id: 'locked', header: 'Locked', size: 10, enableHiding: false, cell: () => null },
  { id: 'a', header: 'A', size: 10, cell: () => null },
  { id: 'b', header: 'B', size: 10, cell: () => null },
];

function TestHarness() {
  const table = useReactTable({
    columns: COLUMNS,
    data: [],
    getCoreRowModel: getCoreRowModel(),
  });
  return <ColumnPicker table={table} />;
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
});
