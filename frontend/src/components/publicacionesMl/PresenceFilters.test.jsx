import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PresenceFilters from './PresenceFilters';
import { activePresenceChips, EMPTY_PRESENCE_FILTERS } from './presenceFilters';

const filters = (overrides = {}) => ({ ...EMPTY_PRESENCE_FILTERS, ...overrides });

describe('presenceFilters', () => {
  it("clears every presence key (Productos' URL keys)", () => {
    expect(EMPTY_PRESENCE_FILTERS).toEqual({ rebate: '', oferta: '', webtransf: '', tiendanube: '', outofcards: '' });
  });

  it('gives one chip per active toggle, labelled the way Productos labels the value, that clears it', () => {
    expect(activePresenceChips(filters({ rebate: 'sin_rebate', outofcards: 'con_out_of_cards' }))).toEqual([
      { id: 'rebate', label: 'Rebate: Sin Rebate', remove: { rebate: '' } },
      { id: 'outofcards', label: 'Out of Cards: Marcados', remove: { outofcards: '' } },
    ]);
    expect(activePresenceChips(filters())).toEqual([]);
  });
});

const openPanel = () => userEvent.click(screen.getByRole('button', { name: /Filtros de presencia/ }));

describe('PresenceFilters', () => {
  it('keeps the five toggles behind one button, as Productos keeps them behind "Filtros Avanzados"', async () => {
    render(<PresenceFilters filters={filters()} setFilters={vi.fn()} />);
    expect(screen.getByText('Presencia:')).toBeInTheDocument();
    const button = screen.getByRole('button', { name: /Filtros de presencia/ });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    await openPanel();
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getAllByRole('combobox')).toHaveLength(5);
  });

  it('closes the panel on Escape and on a click outside it', async () => {
    render(
      <>
        <PresenceFilters filters={filters()} setFilters={vi.fn()} />
        <p>afuera</p>
      </>,
    );
    await openPanel();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    await openPanel();
    await userEvent.click(screen.getByText('afuera'));
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('the button counts the active toggles', () => {
    render(<PresenceFilters filters={filters({ rebate: 'con_rebate', oferta: 'sin_oferta' })} setFilters={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Filtros de presencia (2 activos)' })).toBeInTheDocument();
  });

  it("offers Productos' five toggles with Productos' options", async () => {
    render(<PresenceFilters filters={filters()} setFilters={vi.fn()} />);
    await openPanel();
    const options = (name) => [...screen.getByRole('combobox', { name }).options].map((o) => o.textContent);
    expect(options('Rebate')).toEqual(['Todos', 'Con Rebate', 'Sin Rebate']);
    expect(options('Mejor Oferta')).toEqual(['Todos', 'Con Oferta', 'Sin Oferta']);
    expect(options('Web Transferencia')).toEqual(['Todos', 'Con Web Transf.', 'Sin Web Transf.']);
    expect(options('Tienda Nube')).toEqual(['Todos', 'Con Descuento', 'Sin Descuento', 'No Publicado']);
    expect(options('Out of Cards')).toEqual(['Todos', 'Marcados', 'No Marcados']);
  });

  it('writes the picked value to the URL and "Todos" clears it', async () => {
    const setFilters = vi.fn();
    render(<PresenceFilters filters={filters({ oferta: 'con_oferta' })} setFilters={setFilters} />);
    await openPanel();
    expect(screen.getByRole('combobox', { name: 'Mejor Oferta' })).toHaveValue('con_oferta');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Tienda Nube' }), 'no_publicado');
    expect(setFilters).toHaveBeenLastCalledWith({ tiendanube: 'no_publicado' });
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Mejor Oferta' }), 'todos');
    expect(setFilters).toHaveBeenLastCalledWith({ oferta: '' });
  });

  it('shows a removable chip per active toggle and a control that clears them all', async () => {
    const setFilters = vi.fn();
    render(<PresenceFilters filters={filters({ webtransf: 'con_web_transf', tiendanube: 'sin_descuento' })} setFilters={setFilters} />);
    await userEvent.click(screen.getByRole('button', { name: 'Quitar Web Transferencia: Con Web Transf.' }));
    expect(setFilters).toHaveBeenLastCalledWith({ webtransf: '' });
    expect(screen.getByRole('button', { name: 'Quitar Tienda Nube: Sin Descuento' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Limpiar presencia/ }));
    expect(setFilters).toHaveBeenLastCalledWith(EMPTY_PRESENCE_FILTERS);
  });

  it('uses no emoji: the toggles that carry an icon draw a lucide one, hidden from assistive tech', async () => {
    const { container } = render(
      <PresenceFilters filters={filters({ tiendanube: 'no_publicado', rebate: 'con_rebate' })} setFilters={vi.fn()} />,
    );
    await openPanel();
    expect(container.textContent).not.toMatch(/\p{Extended_Pictographic}/u);
    const icons = container.querySelectorAll('label svg');
    expect(icons).toHaveLength(3); // Rebate, Web Transferencia, Tienda Nube, as in Productos
    icons.forEach((icon) => expect(icon).toHaveAttribute('aria-hidden', 'true'));
  });

  it('shows no chips while no toggle is active', () => {
    render(<PresenceFilters filters={filters()} setFilters={vi.fn()} />);
    expect(screen.queryByRole('list', { name: 'Filtros de presencia activos' })).not.toBeInTheDocument();
  });
});
