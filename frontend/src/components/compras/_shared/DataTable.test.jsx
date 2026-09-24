import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import DataTable from './DataTable';

const COLUMNS = [
  { key: 'id', label: 'Job' },
  { key: 'nombre', label: 'Nombre' },
];

const ROWS = [
  { id: 1, nombre: 'Alpha' },
  { id: 2, nombre: 'Beta' },
];

function renderCell(row, col) {
  return col.key === 'id' ? `#${row.id}` : row[col.key];
}

describe('DataTable expand slot', () => {
  it('omitted expand props leave markup unchanged', () => {
    const { container } = render(
      <DataTable columns={COLUMNS} rows={ROWS} renderCell={renderCell} />,
    );
    const rows = container.querySelectorAll('table tbody tr');
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelectorAll('td')).toHaveLength(2);
    expect(screen.queryByText('detail-1')).toBeNull();
    expect(screen.queryByText('detail-2')).toBeNull();
  });

  it('renders colspan expand under the matching row only', () => {
    const { container } = render(
      <DataTable
        columns={COLUMNS}
        rows={ROWS}
        renderCell={renderCell}
        expandedRowId={1}
        renderExpandedRow={(row) => <div>detail-{row.id}</div>}
      />,
    );
    const rows = container.querySelectorAll('table tbody tr');
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toContain('#1');
    expect(rows[1].textContent).toBe('detail-1');
    expect(rows[1].querySelector('td').getAttribute('colspan')).toBe('2');
    expect(rows[2].textContent).toContain('#2');
    expect(screen.queryByText('detail-2')).toBeNull();
  });
});
