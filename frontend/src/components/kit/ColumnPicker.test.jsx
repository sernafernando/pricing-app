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
