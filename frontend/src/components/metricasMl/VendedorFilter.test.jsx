/**
 * vpf-metricas-canal-fe C5 (mockup 2): the Por fuera salesperson filter -- "Todos", the top salespeople by documents
 * as chips with their counts (`facets.vendedor_documentos`), the rest in "Otro".
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VendedorFilter from './VendedorFilter';

const OPTIONS = ['Vendedor Dos', 'Vendedora Uno', 'Vendedora Tres', 'Vendedor Cuatro', 'Vendedora Cinco'];
const COUNTS = { 'Vendedora Uno': 96, 'Vendedor Dos': 31, 'Vendedora Tres': 14, 'Vendedor Cuatro': 8, 'Vendedora Cinco': 3 };
const chips = (props = {}) => {
  const onChange = vi.fn();
  render(<VendedorFilter options={OPTIONS} counts={COUNTS} value="" onChange={onChange} variant="chips" {...props} />);
  return onChange;
};
const chipNames = () =>
  within(screen.getByRole('group', { name: 'Vendedores' }))
    .getAllByRole('button')
    .map((b) => b.textContent);

describe('VendedorFilter chips (Por fuera)', () => {
  it('shows "Todos" and the top 3 salespeople by documents with their counts, the rest in "Otro"', () => {
    chips();

    expect(chipNames()).toEqual(['Todos', 'Vendedora Uno · 96', 'Vendedor Dos · 31', 'Vendedora Tres · 14']);
    const otro = screen.getByRole('combobox', { name: 'Vendedor' });
    expect(within(otro).getAllByRole('option').map((o) => o.textContent)).toEqual(['Otro', 'Vendedor Cuatro · 8', 'Vendedora Cinco · 3']);
  });

  it('a chip filters by its salesperson, and pressing it again clears', async () => {
    const onChange = chips();
    await userEvent.click(screen.getByRole('button', { name: 'Vendedor Dos · 31' }));
    expect(onChange).toHaveBeenCalledWith('Vendedor Dos');
  });

  it('a salesperson chosen from "Otro" joins the chips, pressed', async () => {
    const onChange = chips({ value: 'Vendedora Cinco' });

    expect(screen.getByRole('button', { name: 'Vendedora Cinco · 3' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Todos' })).toHaveAttribute('aria-pressed', 'false');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Vendedor' }), 'Vendedor Cuatro');
    expect(onChange).toHaveBeenCalledWith('Vendedor Cuatro');
  });

  it('without counts, the first salespeople in the board\'s order are the chips (no count shown)', () => {
    chips({ counts: undefined });
    expect(chipNames()).toEqual(['Todos', 'Vendedor Dos', 'Vendedora Uno', 'Vendedora Tres']);
  });
});

describe('VendedorFilter select (Todo, unchanged)', () => {
  it('is one dropdown with every salesperson', () => {
    render(<VendedorFilter options={OPTIONS} counts={COUNTS} value="" onChange={() => {}} />);
    const select = screen.getByRole('combobox', { name: 'Vendedor' });
    expect(within(select).getAllByRole('option')).toHaveLength(OPTIONS.length + 1);
    expect(screen.queryByRole('group', { name: 'Vendedores' })).toBeNull();
  });
});

describe('VendedorFilter with several salespeople from a link (a load that imported more than one)', () => {
  it('chips: every chosen salesperson is a pressed chip and "Todos" is not pressed', () => {
    chips({ value: ['Vendedora Cinco', 'Vendedor Cuatro'] });
    const group = screen.getByRole('group', { name: 'Vendedores' });
    expect(within(group).getByRole('button', { name: /^Todos$/ })).toHaveAttribute('aria-pressed', 'false');
    expect(within(group).getByRole('button', { name: /Vendedora Cinco/ })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group).getByRole('button', { name: /Vendedor Cuatro/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('select: says how many salespeople are chosen instead of "Todos los vendedores"', () => {
    render(<VendedorFilter options={OPTIONS} value={['Vendedora Uno', 'Vendedor Dos']} onChange={() => {}} />);
    const select = screen.getByRole('combobox', { name: 'Vendedor' });
    expect(select.selectedOptions[0]).toHaveTextContent('2 vendedores');
  });

  it('one chosen salesperson as a list works like the plain name', () => {
    chips({ value: ['Vendedor Dos'] });
    expect(screen.getByRole('button', { name: /Vendedor Dos/ })).toHaveAttribute('aria-pressed', 'true');
  });
});
