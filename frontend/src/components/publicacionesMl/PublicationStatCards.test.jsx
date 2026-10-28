/**
 * PublicationStatCards (S12d4): Productos' stat cards over the screen's filters; a click applies the card's filter.
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PublicationStatCards from './PublicationStatCards';
import { STAT_FILTER_KEYS } from './statCards';

const STATS = {
  total: 40,
  con_stock: 30,
  con_precio: 35,
  con_stock_sin_precio: 3,
  nuevos: 5,
  nuevos_sin_precio: 2,
  oferta_sin_rebate: 4,
};
const NO_STAT_FILTER = Object.fromEntries(STAT_FILTER_KEYS.map((key) => [key, key === 'stock' ? [] : '']));

function setup(props = {}) {
  const onApply = vi.fn();
  const onReset = vi.fn();
  const onRetry = vi.fn();
  render(
    <PublicationStatCards
      state={{ data: { stats: STATS, can_see_margin: false }, loading: false, error: null }}
      filters={NO_STAT_FILTER}
      canSeeMargin={false}
      onApply={onApply}
      onReset={onReset}
      onRetry={onRetry}
      {...props}
    />,
  );
  return { onApply, onReset, onRetry };
}

describe('PublicationStatCards', () => {
  it('shows each count as a button that applies its filter, clearing the other card filters', async () => {
    const { onApply } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'Stock sin $: 3' }));
    expect(onApply).toHaveBeenCalledWith({
      ...Object.fromEntries(STAT_FILTER_KEYS.map((key) => [key, ''])),
      stock: ['erp_con_stock'],
      precio: 'sin_precio',
    });
  });

  it('Total Productos clears the filters', async () => {
    const { onReset, onApply } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'Total Productos: 40' }));
    expect(onReset).toHaveBeenCalledTimes(1);
    expect(onApply).not.toHaveBeenCalled();
  });

  it('marks the card whose filter is on', () => {
    setup({ filters: { ...NO_STAT_FILTER, oferta: 'con_oferta', rebate: 'sin_rebate' } });
    expect(screen.getByRole('button', { name: 'Oferta sin Rebate: 4' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Con Stock: 30' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows the markup cards only to who sees the margin', () => {
    setup();
    expect(screen.queryByText('Markup Negativo')).not.toBeInTheDocument();
  });

  it('with the margin, the markup cards apply their negative filter', async () => {
    const stats = { ...STATS, markup_negativo_clasica: 6, markup_negativo_rebate: 1, markup_negativo_oferta: 0, markup_negativo_web: 2 };
    const { onApply } = setup({ canSeeMargin: true, state: { data: { stats, can_see_margin: true }, loading: false, error: null } });
    await userEvent.click(screen.getByRole('button', { name: 'Web: 2' }));
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ mkwebtransf: 'negativo', mkclasica: '' }));
  });

  it('while loading the first time, the figures are unknown, not 0', () => {
    setup({ state: { data: null, loading: true, error: null } });
    expect(screen.getByRole('button', { name: 'Con Stock: cargando' })).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('a failed read says so and offers to retry', async () => {
    const { onRetry } = setup({ state: { data: null, loading: false, error: new Error('HTTP 503') } });
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudieron cargar los totales');
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('says when a publication markup filter is on: the cards do not apply it', () => {
    setup({ markupNotice: true });
    expect(screen.getByText(/no aplican el filtro de markup de la publicación/)).toBeInTheDocument();
  });
});

describe('the Sin MLA card (S12d4c)', () => {
  const SIN_MLA = { ...STATS, sin_mla: 12, sin_mla_con_stock: 7, sin_mla_sin_stock: 5, sin_mla_nuevos: 2 };
  const state = (stats) => ({ data: { stats, can_see_margin: false }, loading: false, error: null });

  it('in the Producto view a click lists the products without MLA, clearing the publication filters', async () => {
    const filters = { ...NO_STAT_FILTER, estado: ['active'], marcas: ['TP-Link'] };
    const { onApply } = setup({ state: state(SIN_MLA), filters, sinMla: true });
    const group = screen.getByRole('group', { name: 'Sin MLA' });
    await userEvent.click(within(group).getByRole('button', { name: 'Con Stock: 7' }));
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ mla: 'sin_mla', stock: ['erp_con_stock'], estado: '' }));
    expect(onApply.mock.calls[0][0]).not.toHaveProperty('marcas');
  });

  it('shows "–" when the count does not apply (a publication filter is on)', () => {
    setup({ state: state(STATS), sinMla: true });
    const total = within(screen.getByRole('group', { name: 'Sin MLA' })).getByRole('button', { name: 'Total: no disponible' });
    expect(total).toHaveTextContent('–');
  });

  it('is not in the publication view', () => {
    setup({ state: state(SIN_MLA) });
    expect(screen.queryByRole('group', { name: 'Sin MLA' })).not.toBeInTheDocument();
  });
});
