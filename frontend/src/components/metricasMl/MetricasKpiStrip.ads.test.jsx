import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import MetricasKpiStrip from './MetricasKpiStrip';
import { BOARD_RESPONSE } from '../../test/visual/metricasMlFixtures';
import { ADS_KPIS } from './adsFixtures';

const OFF = BOARD_RESPONSE.kpis;
const cardOf = (label) => screen.getByText(label, { selector: 'span' }).closest('div[class*="card"]');

describe('MetricasKpiStrip with ads subtracted', () => {
  it('shows no adjustment marks with the toggle off', () => {
    render(<MetricasKpiStrip kpis={{ ...OFF, ads: null }} canSeeMargin groupBy="product" />);
    expect(screen.queryByText('Ajustado')).not.toBeInTheDocument();
    expect(screen.queryByText(/Original:/)).not.toBeInTheDocument();
  });

  it('marks Total Gauss and Markup as adjusted and strikes the original Total Gauss through', () => {
    render(<MetricasKpiStrip kpis={{ ...OFF, ads: { ...ADS_KPIS, subtracted_total: 1000000 } }} canSeeMargin groupBy="product" />);
    const gauss = within(cardOf('Total Gauss'));
    expect(gauss.getByText('Ajustado')).toBeInTheDocument();
    expect(gauss.getByText('$ 14.120.900,10')).toBeInTheDocument();
    const original = gauss.getByText('$ 15.120.900,10');
    expect(original.tagName).toBe('S');
    expect(within(cardOf('Markup promedio')).getByText('Ajustado')).toBeInTheDocument();
  });

  it('leaves the other cards untouched', () => {
    render(<MetricasKpiStrip kpis={{ ...OFF, ads: ADS_KPIS }} canSeeMargin groupBy="product" />);
    expect(within(cardOf('Unidades vendidas')).queryByText('Ajustado')).not.toBeInTheDocument();
    expect(within(cardOf('Facturado bruto')).queryByText('Ajustado')).not.toBeInTheDocument();
  });
});
