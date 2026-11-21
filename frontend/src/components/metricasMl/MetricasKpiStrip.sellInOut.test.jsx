import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import MetricasKpiStrip from './MetricasKpiStrip';
import { BOARD_RESPONSE } from '../../test/visual/metricasMlFixtures';

// The board's KPIs with every toggle off (no publicidad, no "Costos TP"); each test sets its own sell figures.
const OFF = BOARD_RESPONSE.kpis;
// Costo SI T3 D1: the cost is costo SI; the sell out is added to the profit ("c/ SO"), no sell in.
const SELL = {
  sell_out: 30000,
  sell_out_pendientes: 0,
  sell_out_estimados: 0,
  costo: 1000000,
  total_gauss: 14150900.1,
  markup_pct: 31.4,
};
const EMPTY = { ...SELL, sell_out: null, total_gauss: null, markup_pct: null };
// The card title is the first span with that text: the "Sell out" card also has a "Sell out" figure line.
const cardOf = (label) => screen.getAllByText(label, { selector: 'span' })[0].closest('div[class*="card"]');
const strip = (kpis, canSeeMargin = true) => render(<MetricasKpiStrip kpis={kpis} canSeeMargin={canSeeMargin} groupBy="product" />);

describe('MetricasKpiStrip with sell out c/ SO', () => {
  it('shows Total Gauss and markup c/ SO under the figures without them', () => {
    strip({ ...OFF, sell_in_out: SELL });

    expect(within(cardOf('Total Gauss')).getByText('$ 14.120.900,10')).toBeInTheDocument();
    expect(within(cardOf('Total Gauss')).getByTestId('kpi-sell-in-out')).toHaveTextContent('C/ SO: $ 14.150.900,10');
    expect(within(cardOf('Markup promedio')).getByTestId('kpi-sell-in-out')).toHaveTextContent('C/ SO: 31,4%');
  });

  it('warns how many sales still have a sell out without its rate', () => {
    strip({ ...OFF, sell_in_out: { ...SELL, sell_out_pendientes: 3 } });

    expect(within(cardOf('Total Gauss')).getByTitle('3 ventas con sell out en dólares sin tipo de cambio: no se suman')).toBeInTheDocument();
  });

  it("keeps Total Gauss' ⚠ and ≈ flags in one block apart from the amount, so ≈ never wraps alone", () => {
    strip({ ...OFF, sell_in_out: { ...SELL, sell_out_pendientes: 12, sell_out_estimados: 3 } });

    const card = within(cardOf('Total Gauss'));
    const pending = card.getByTitle('12 ventas con sell out en dólares sin tipo de cambio: no se suman');
    const estimated = card.getByTitle('3 ventas con tipo de cambio estimado');
    const amount = card.getByTestId('kpi-sell-in-out').querySelector('strong');
    expect(pending.parentElement).toBe(estimated.parentElement);
    expect(estimated.parentElement).not.toBe(amount.parentElement);
    expect(estimated.parentElement.className).toMatch(/sellFlags/);
  });

  it('with no flags, the Total Gauss line holds only the amount (no empty flags block)', () => {
    strip({ ...OFF, sell_in_out: SELL });

    expect(within(cardOf('Total Gauss')).getByTestId('kpi-sell-in-out').querySelector('[class*="sellFlags"]')).toBeNull();
  });

  it('flags how many sales add a sell out on an estimated rate, like the rows do (audit A5)', () => {
    strip({ ...OFF, sell_in_out: { ...SELL, sell_out_estimados: 3 } });

    const estimated = '3 ventas con tipo de cambio estimado';
    expect(within(cardOf('Total Gauss')).getByTitle(estimated)).toHaveTextContent('≈ 3');
    expect(within(cardOf('Sell out')).getByTitle(estimated)).toHaveTextContent('≈ 3');
  });

  it('shows both flags side by side when some sell outs lack a rate and others use an estimate', () => {
    strip({ ...OFF, sell_in_out: { ...SELL, sell_out_pendientes: 2, sell_out_estimados: 3 } });

    const sellOut = within(cardOf('Sell out')).getByTestId('kpi-sell-out');
    expect(within(sellOut).getByTitle('2 ventas con sell out en dólares sin tipo de cambio: no se suman')).toHaveTextContent('2');
    expect(within(sellOut).getByTitle('3 ventas con tipo de cambio estimado')).toHaveTextContent('≈ 3');
  });

  it('shows no estimated-rate flag when every sell out has its final rate', () => {
    strip({ ...OFF, sell_in_out: SELL });

    expect(screen.queryByText(/≈/)).not.toBeInTheDocument();
  });

  it('shows nothing of it when no sale in the period has a sell out', () => {
    strip({ ...OFF, sell_in_out: EMPTY });

    expect(screen.queryByTestId('kpi-sell-in-out')).not.toBeInTheDocument();
  });

  it('shows the sell out and the cost in their own card, with no sell in nor cost with sell in', () => {
    strip({ ...OFF, sell_in_out: SELL });

    const card = cardOf('Sell out');
    expect(within(card).getByTestId('kpi-sell-out')).toHaveTextContent('Sell out$ 30.000,00');
    expect(within(card).getByTestId('kpi-costo')).toHaveTextContent('Costo$ 1.000.000,00');
    expect(within(card).queryByTestId('kpi-sell-in')).not.toBeInTheDocument();
    expect(within(card).queryByTestId('kpi-costo-sell-in')).not.toBeInTheDocument();
    expect(screen.queryByText(/sell in/i)).not.toBeInTheDocument();
  });

  it('leaves out of the card the figures that do not apply', () => {
    // The null cost stands in for the backend's "Costos TP" on response, which leaves out the cost.
    strip({ ...OFF, sell_in_out: { ...SELL, costo: null, sell_out_pendientes: 2 } });

    const card = cardOf('Sell out');
    expect(within(card).getByTestId('kpi-sell-out')).toHaveTextContent('Sell out$ 30.000,00');
    expect(within(card).getByTitle('2 ventas con sell out en dólares sin tipo de cambio: no se suman')).toBeInTheDocument();
    expect(within(card).queryByTestId('kpi-costo')).not.toBeInTheDocument();
  });

  it('has no sell out card when no sale in the period has one, nor without the profit view', () => {
    strip({ ...OFF, sell_in_out: EMPTY });
    expect(screen.queryByText('Sell out', { selector: 'span' })).not.toBeInTheDocument();

    strip({ ...OFF, sell_in_out: SELL }, false);
    expect(screen.queryByText('Sell out', { selector: 'span' })).not.toBeInTheDocument();
  });

  it('shows nothing of it without the figures', () => {
    strip({ ...OFF, sell_in_out: null });

    expect(screen.queryByTestId('kpi-sell-in-out')).not.toBeInTheDocument();
  });
});
