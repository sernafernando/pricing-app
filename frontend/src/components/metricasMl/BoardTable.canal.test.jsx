/**
 * vpf-metricas-canal-fe T2 (S2, C3): the board's Canal column (canal=todo only) and the "Sin producto" rows (a fuera
 * line whose code is no catalog product: negative product id) with '—' in markup and Total Gauss.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import BoardTable from './BoardTable';
import { buildBoardColumns } from './metricasMlColumns';
import { FUERA_ROWS, TODO_ROWS } from '../../test/visual/metricasMlCanalFixtures';

function renderTable(rows, canal, costo) {
  render(
    <BoardTable
      rows={rows}
      columns={buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product', canal, costo })}
      groupBy="product"
      canSeeMargin
      expanded={new Set()}
      subRows={{}}
      onToggleExpand={() => {}}
      sort="gross"
      sortDesc
      onSort={() => {}}
      now={new Date('2026-10-31T18:00:00Z')}
    />,
  );
}

const rowOf = (title) => screen.getByText(title, { selector: 'span' }).closest('tr');
const cell = (tr, id) => tr.querySelector(`td[data-col-id="${id}"]`);

describe('buildBoardColumns: Canal', () => {
  it('adds Canal right after Producto only with canal=todo', () => {
    const ids = (canal) => buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product', canal }).map((c) => c.id);
    expect(ids('todo').slice(0, 2)).toEqual(['producto', 'canal']);
    expect(ids('fuera')).not.toContain('canal');
    expect(ids('ml')).not.toContain('canal');
    expect(ids(undefined)).toEqual(ids('ml'));
  });
});

describe('BoardTable with canal=todo', () => {
  it('says each row\'s channel: "ML", "Por fuera" or "ML + fuera"', () => {
    renderTable(TODO_ROWS, 'todo');

    expect(screen.getByRole('columnheader', { name: 'Canal' })).toBeInTheDocument();
    expect(cell(rowOf(TODO_ROWS[0].title), 'canal')).toHaveTextContent('ML + fuera');
    expect(cell(rowOf(TODO_ROWS[1].title), 'canal')).toHaveTextContent(/^ML$/);
    expect(cell(rowOf(TODO_ROWS[2].title), 'canal')).toHaveTextContent('Por fuera');
  });

  it('a sin producto row says so and shows "—" in markup and Total Gauss, its Venta still counted', () => {
    renderTable(TODO_ROWS, 'todo');

    const tr = rowOf('PC armada de prueba R5 16GB (Manual)');
    expect(within(cell(tr, 'producto')).getByText('Sin producto')).toBeInTheDocument();
    expect(cell(tr, 'markup')).toHaveTextContent(/^—$/);
    expect(cell(tr, 'total_gauss')).toHaveTextContent(/^—$/);
    expect(cell(tr, 'gross')).toHaveTextContent('$ 5.480.200,40');
  });

  it('a sin producto row with a margin from the answer still reads "—" (there is no cost to subtract)', () => {
    const row = { ...TODO_ROWS[4], total_gauss: 0, markup_pct: 0 };
    renderTable([row], 'todo');

    const tr = rowOf(row.title);
    expect(cell(tr, 'markup')).toHaveTextContent(/^—$/);
    expect(cell(tr, 'total_gauss')).toHaveTextContent(/^—$/);
  });
});

describe('buildBoardColumns: the channel cost (C5)', () => {
  const cols = (canal, opts = {}) => buildBoardColumns({ canSeeMargin: true, periodLabel: 'mes', groupBy: 'product', canal, ...opts });
  const ids = (columns) => columns.map((c) => c.id);

  it('Por fuera: "Costo (Costo D)" in Resultado financiero right after Total Gauss; the label follows the selector', () => {
    const fuera = cols('fuera', { costo: 'costo_d' });
    const at = ids(fuera).indexOf('costo_canal');
    expect(ids(fuera)[at - 1]).toBe('total_gauss');
    expect(fuera[at]).toMatchObject({ group: 'resultado', header: 'Costo (Costo D)' });
    expect(cols('fuera', { costo: 'costo' }).find((c) => c.id === 'costo_canal').header).toBe('Costo (Costo)');
  });

  it('Todo and ML: no channel cost column (mockup 1); ML\'s sell-in "Costo" stays as today', () => {
    const todo = cols('todo', { costo: 'costo_d' });
    expect(ids(todo)).not.toContain('costo_canal');
    expect(ids(todo.filter((c) => c.group === 'resultado'))).toEqual(['gross', 'total_gauss']);
    expect(ids(cols('ml'))).not.toContain('costo_canal');
    expect(cols('ml').find((c) => c.id === 'costo')).toMatchObject({ group: 'sellin', header: 'Costo' });
  });

  it('is a margin column (S6): gone without the profit view', () => {
    expect(ids(buildBoardColumns({ canSeeMargin: false, periodLabel: 'mes', groupBy: 'product', canal: 'fuera' }))).not.toContain('costo_canal');
  });
});

describe('BoardTable: the channel cost cell (C5)', () => {
  it('shows rows[].costo, and "—" when null or on a sin producto row', () => {
    renderTable(FUERA_ROWS, 'fuera', 'costo_d');

    expect(screen.getByRole('columnheader', { name: 'Costo (Costo D)' })).toBeInTheDocument();
    expect(cell(rowOf('Notebook de prueba 15" R7 16GB'), 'costo_canal')).toHaveTextContent('$ 19.400.000,00');
    expect(cell(rowOf('PC armada de prueba R5 16GB (Manual)'), 'costo_canal')).toHaveTextContent(/^—$/);
  });

  it('a sin producto row reads "—" even if the answer had a cost', () => {
    const row = { ...FUERA_ROWS[2], costo: 1000 };
    renderTable([row], 'fuera', 'costo_d');
    expect(cell(rowOf(row.title), 'costo_canal')).toHaveTextContent(/^—$/);
  });
});
