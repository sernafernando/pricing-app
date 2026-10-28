import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import MetricasKpiStrip from './MetricasKpiStrip';
import { BOARD_RESPONSE } from '../../test/visual/metricasMlFixtures';

const OFF = BOARD_RESPONSE.kpis;
const SELL = {
  sell_in: 120000,
  sell_out: 30000,
  sell_out_pendientes: 0,
  sell_out_estimados: 0,
  costo: 1000000,
  costo_sell_in: 880000,
  total_gauss: 14270900.1,
  markup_pct: 31.4,
};
const cardOf = (label) => screen.getByText(label, { selector: 'span' }).closest('div[class*="card"]');
const strip = (kpis, canSeeMargin = true) => render(<MetricasKpiStrip kpis={kpis} canSeeMargin={canSeeMargin} groupBy="product" />);

describe('MetricasKpiStrip with sell in / sell out', () => {
  it('shows Total Gauss and markup with them under the figures without them', () => {
    strip({ ...OFF, sell_in_out: SELL });

    expect(within(cardOf('Total Gauss')).getByText('$ 14.120.900,10')).toBeInTheDocument();
    expect(within(cardOf('Total Gauss')).getByTestId('kpi-sell-in-out')).toHaveTextContent('C/ sell in/out: $ 14.270.900,10');
    expect(within(cardOf('Markup promedio')).getByTestId('kpi-sell-in-out')).toHaveTextContent('C/ sell in/out: 31,4%');
  });

  it('warns how many sales still have a sell out without its rate', () => {
    strip({ ...OFF, sell_in_out: { ...SELL, sell_out_pendientes: 3 } });

    expect(within(cardOf('Total Gauss')).getByTitle('3 ventas con sell out en dólares sin tipo de cambio: no se suman')).toBeInTheDocument();
  });

  it('flags how many sales add a sell out on an estimated rate, like the rows do (audit A5)', () => {
    strip({ ...OFF, sell_in_out: { ...SELL, sell_out_estimados: 3 } });

    const estimated = '3 ventas con tipo de cambio estimado';
    expect(within(cardOf('Total Gauss')).getByTitle(estimated)).toHaveTextContent('≈ 3');
    expect(within(cardOf('Sell in / Sell out')).getByTitle(estimated)).toHaveTextContent('≈ 3');
  });

  it('shows no estimated-rate flag when every sell out has its final rate', () => {
    strip({ ...OFF, sell_in_out: SELL });

    expect(screen.queryByText(/≈/)).not.toBeInTheDocument();
  });

  it('shows nothing of it when no sale in the period has a sell in or a sell out', () => {
    strip({ ...OFF, sell_in_out: { ...SELL, sell_in: null, sell_out: null, costo_sell_in: null, total_gauss: null, markup_pct: null } });

    expect(screen.queryByTestId('kpi-sell-in-out')).not.toBeInTheDocument();
  });

  it('shows the sell in and sell out totals and the cost without and with sell in in their own card', () => {
    strip({ ...OFF, sell_in_out: SELL });

    const card = cardOf('Sell in / Sell out');
    expect(within(card).getByTestId('kpi-sell-in')).toHaveTextContent('Sell in$ 120.000,00');
    expect(within(card).getByTestId('kpi-sell-out')).toHaveTextContent('Sell out$ 30.000,00');
    expect(within(card).getByTestId('kpi-costo')).toHaveTextContent('Costo$ 1.000.000,00');
    expect(within(card).getByTestId('kpi-costo-sell-in')).toHaveTextContent('Costo c/ sell in$ 880.000,00');
  });

  it('leaves out of the card the figures that do not apply', () => {
    // Only a sell out in the period; with "Costos TP" on there is no cost with sell in either.
    strip({ ...OFF, sell_in_out: { ...SELL, sell_in: null, costo: null, costo_sell_in: null, sell_out_pendientes: 2 } });

    const card = cardOf('Sell in / Sell out');
    expect(within(card).getByTestId('kpi-sell-out')).toHaveTextContent('Sell out$ 30.000,00');
    expect(within(card).getByTitle('2 ventas con sell out en dólares sin tipo de cambio: no se suman')).toBeInTheDocument();
    expect(within(card).queryByTestId('kpi-sell-in')).not.toBeInTheDocument();
    expect(within(card).queryByTestId('kpi-costo')).not.toBeInTheDocument();
    expect(within(card).queryByTestId('kpi-costo-sell-in')).not.toBeInTheDocument();
  });

  it('has no sell in / sell out card when no sale in the period has one, nor without the profit view', () => {
    strip({ ...OFF, sell_in_out: { ...SELL, sell_in: null, sell_out: null, costo_sell_in: null, total_gauss: null, markup_pct: null } });
    expect(screen.queryByText('Sell in / Sell out')).not.toBeInTheDocument();

    strip({ ...OFF, sell_in_out: SELL }, false);
    expect(screen.queryByText('Sell in / Sell out')).not.toBeInTheDocument();
  });

  it('shows nothing of it without the figures', () => {
    strip({ ...OFF, sell_in_out: null });

    expect(screen.queryByTestId('kpi-sell-in-out')).not.toBeInTheDocument();
  });
});
