import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PromoFilters from './PromoFilters';
import { EMPTY_PROMO_FILTERS } from './promoFilters';

const filters = (overrides = {}) => ({ ...EMPTY_PROMO_FILTERS, ...overrides });
const openPanel = () => userEvent.click(screen.getByRole('button', { name: /Filtros de promociones/ }));

describe('PromoFilters', () => {
  it("offers Productos' promo types, promo state and wholesale prices behind one button", async () => {
    render(<PromoFilters filters={filters()} setFilters={vi.fn()} />);
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    await openPanel();
    expect(screen.getByRole('checkbox', { name: 'Campaña' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Lightning' })).toBeInTheDocument();
    const options = (name) => [...screen.getByRole('combobox', { name }).options].map((o) => o.textContent);
    expect(options('Estado de promo')).toEqual(['Disponible', 'Aplicada', 'Sin aplicar']);
    expect(options('Precios mayoristas')).toEqual(['Todos', 'Con precios mayoristas']);
  });

  it('writes each pick to the URL', async () => {
    const setFilters = vi.fn();
    render(<PromoFilters filters={filters({ promo_tipos: ['DEAL'] })} setFilters={setFilters} />);
    await openPanel();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Smart' }));
    expect(setFilters).toHaveBeenLastCalledWith({ promo_tipos: ['DEAL', 'SMART'] });
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Estado de promo' }), 'Aplicada');
    expect(setFilters).toHaveBeenLastCalledWith({ promo_estado: 'aplicada' });
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Estado de promo' }), 'Disponible');
    expect(setFilters).toHaveBeenLastCalledWith({ promo_estado: '' });
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Precios mayoristas' }), 'Con precios mayoristas');
    expect(setFilters).toHaveBeenLastCalledWith({ pxq: 'con_pxq' });
  });

  it('shows a removable chip per active value and a control that clears them all', async () => {
    const setFilters = vi.fn();
    render(
      <PromoFilters filters={filters({ promo_tipos: ['DEAL'], promo_estado: 'sin_aplicar', pxq: 'con_pxq' })} setFilters={setFilters} />,
    );
    expect(screen.getByRole('button', { name: 'Filtros de promociones (3 activos)' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Quitar Promo: Deal' }));
    expect(setFilters).toHaveBeenLastCalledWith({ promo_tipos: [] });
    await userEvent.click(screen.getByRole('button', { name: 'Quitar Estado de promo: Sin aplicar' }));
    expect(setFilters).toHaveBeenLastCalledWith({ promo_estado: '' });
    await userEvent.click(screen.getByRole('button', { name: 'Quitar Con precios mayoristas' }));
    expect(setFilters).toHaveBeenLastCalledWith({ pxq: '' });
    await userEvent.click(screen.getByRole('button', { name: /Limpiar promos/ }));
    expect(setFilters).toHaveBeenLastCalledWith(EMPTY_PROMO_FILTERS);
  });
});
