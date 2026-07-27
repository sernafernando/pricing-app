/**
 * Tests for ParesTable.jsx (sub-pm-bulk-assignment Slice 3) — a PURE
 * presentational (marca, categoria) pair table. Owns NO data fetching and
 * NO business logic: checked state, pairs, and callbacks all come from the
 * parent as props.
 *
 * Scope (per design D5/sizing + spec "Pair table with filters and
 * select-all-filtered"):
 *   - Renders one row per pair.
 *   - Checkbox reflects the incoming `checked` Set.
 *   - Toggling a checkbox calls `onToggle(marca, categoria)`.
 *   - Marca filter is a debounced, case-insensitive TEXT input.
 *   - Categoria filter is a plain <select> with "Todas".
 *   - "Select all filtered" selects exactly what filters currently show.
 *   - Pairs with no titular render "Sin titular" muted, never blank, and
 *     stay selectable.
 *   - Empty state renders a real designed message (launch-day primary state).
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ParesTable from './ParesTable';
import { parKey } from './parKey';

const PARES = [
  { marca: 'Samsung', categoria: 'Celulares', usuario_id: 7, usuario_nombre: 'Otro PM' },
  { marca: 'Samsung', categoria: 'Televisores', usuario_id: null, usuario_nombre: null },
  { marca: 'LG', categoria: 'Celulares', usuario_id: 3, usuario_nombre: 'Ana' },
];

function renderTable(props = {}) {
  const defaultProps = {
    pares: PARES,
    checked: new Set(),
    onToggle: vi.fn(),
    onSelectAllFiltered: vi.fn(),
  };
  return render(<ParesTable {...defaultProps} {...props} />);
}

describe('ParesTable', () => {
  it('renders one row per pair', () => {
    renderTable();
    const filas = screen.getAllByRole('row');
    expect(within(filas[1]).getByText('Samsung')).toBeInTheDocument();
    expect(within(filas[2]).getByText('Samsung')).toBeInTheDocument();
    expect(within(filas[3]).getByText('LG')).toBeInTheDocument();
  });

  it('checkbox reflects the incoming checked set', () => {
    renderTable({ checked: new Set([parKey('Samsung', 'Celulares')]) });
    const checkbox = screen.getByRole('checkbox', { name: /Samsung.*Celulares/i });
    expect(checkbox).toBeChecked();
    const other = screen.getByRole('checkbox', { name: /LG.*Celulares/i });
    expect(other).not.toBeChecked();
  });

  it('toggling a checkbox calls onToggle with marca and categoria', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    renderTable({ onToggle });
    const checkbox = screen.getByRole('checkbox', { name: /LG.*Celulares/i });
    await user.click(checkbox);
    expect(onToggle).toHaveBeenCalledWith('LG', 'Celulares');
  });

  it('marca text filter is case-insensitive and hides non-matching rows', async () => {
    const user = userEvent.setup();
    renderTable();
    const filtro = screen.getByLabelText(/marca/i);
    await user.type(filtro, 'samsung');
    await waitFor(() => {
      expect(screen.getAllByText('Samsung')).toHaveLength(2);
      expect(screen.queryByText('LG')).not.toBeInTheDocument();
    });
  });

  it('categoria select filters rows', async () => {
    const user = userEvent.setup();
    renderTable();
    const select = screen.getByLabelText(/categor/i);
    await user.selectOptions(select, 'Televisores');
    expect(screen.queryByText('LG')).not.toBeInTheDocument();
    expect(screen.getAllByText('Samsung')).toHaveLength(1);
  });

  it('select all filtered selects only what filters currently show', async () => {
    const user = userEvent.setup();
    const onSelectAllFiltered = vi.fn();
    renderTable({ onSelectAllFiltered });
    const filtro = screen.getByLabelText(/marca/i);
    await user.type(filtro, 'samsung');
    await waitFor(() => {
      expect(screen.queryByText('LG')).not.toBeInTheDocument();
    });
    const boton = screen.getByRole('button', { name: /seleccionar todo/i });
    await user.click(boton);
    expect(onSelectAllFiltered).toHaveBeenCalledWith([
      { marca: 'Samsung', categoria: 'Celulares' },
      { marca: 'Samsung', categoria: 'Televisores' },
    ]);
  });

  it('untitled pairs render "Sin titular" muted and stay selectable', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    renderTable({ onToggle });
    const fila = screen.getByText('Sin titular').closest('tr');
    expect(fila).toBeInTheDocument();
    const checkbox = within(fila).getByRole('checkbox');
    expect(checkbox).not.toBeDisabled();
    await user.click(checkbox);
    expect(onToggle).toHaveBeenCalledWith('Samsung', 'Televisores');
  });

  it('renders a real empty state message when there are no pairs', () => {
    renderTable({ pares: [] });
    expect(screen.getByText(/no hay pares/i)).toBeInTheDocument();
  });

  it('renders a distinct message when filters match nothing (not the no-pairs message)', async () => {
    const user = userEvent.setup();
    renderTable();
    const filtro = screen.getByLabelText(/marca/i);
    await user.type(filtro, 'nadie-tiene-esta-marca');
    await waitFor(() => {
      expect(screen.getByText(/ning[uú]n par coincide/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/no hay pares marca\/categor/i)).not.toBeInTheDocument();
  });

  it('pair keys do not collide when a marca itself contains the separator character', async () => {
    // Regression guard for the reliability-review finding: a naive
    // `${marca}|${categoria}` template key means marca "A|B" + categoria "C"
    // collides with marca "A" + categoria "B|C". `parKey` must escape this
    // away (e.g. via JSON.stringify) so both pairs stay independently
    // selectable.
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const paresConPipe = [
      { marca: 'A|B', categoria: 'C', usuario_id: 1, usuario_nombre: 'Uno' },
      { marca: 'A', categoria: 'B|C', usuario_id: 2, usuario_nombre: 'Dos' },
    ];
    expect(parKey('A|B', 'C')).not.toBe(parKey('A', 'B|C'));

    const checked = new Set([parKey('A|B', 'C')]);
    render(
      <ParesTable pares={paresConPipe} checked={checked} onToggle={onToggle} onSelectAllFiltered={vi.fn()} />,
    );

    const filas = screen.getAllByRole('row');
    const primeraChk = within(filas[1]).getByRole('checkbox');
    const segundaChk = within(filas[2]).getByRole('checkbox');
    expect(primeraChk).toBeChecked();
    expect(segundaChk).not.toBeChecked();

    await user.click(segundaChk);
    expect(onToggle).toHaveBeenCalledWith('A', 'B|C');
    // Toggling the second pair must never flip the first's checked state.
    expect(primeraChk).toBeChecked();
  });
});
