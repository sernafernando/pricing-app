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

  it('shows nothing of it when no sale in the period has a sell in or a sell out', () => {
    strip({ ...OFF, sell_in_out: { ...SELL, sell_in: null, sell_out: null, costo_sell_in: null, total_gauss: null, markup_pct: null } });

    expect(screen.queryByTestId('kpi-sell-in-out')).not.toBeInTheDocument();
  });

  it('shows nothing of it without the figures', () => {
    strip({ ...OFF, sell_in_out: null });

    expect(screen.queryByTestId('kpi-sell-in-out')).not.toBeInTheDocument();
  });
});
