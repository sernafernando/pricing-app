import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import MetricasKpiStrip from './MetricasKpiStrip';
import { BOARD_RESPONSE } from '../../test/visual/metricasMlFixtures';
import { TP_KPIS } from './tpFixtures';

const OFF = BOARD_RESPONSE.kpis;
const cardOf = (label) => screen.getByText(label, { selector: 'span' }).closest('div[class*="card"]');
const strip = (kpis, canSeeMargin = true) => render(<MetricasKpiStrip kpis={kpis} canSeeMargin={canSeeMargin} groupBy="product" />);

describe('MetricasKpiStrip with Costos TP', () => {
  it('has no Total TP card and no TP note on the markup with the toggle off', () => {
    strip({ ...OFF, total_tp: null });
    expect(screen.queryByText('Total TP')).not.toBeInTheDocument();
    expect(screen.queryByText(/costo TP/)).not.toBeInTheDocument();
  });

  it('shows Total TP right after Total Gauss, which stays', () => {
    strip({ ...OFF, total_tp: { value: 3125400.5, incompletos: 0 } });
    const labels = [...document.querySelectorAll('div[class*="label"] > span:first-child')].map((el) => el.textContent);
    expect(labels.indexOf('Total TP')).toBe(labels.indexOf('Total Gauss') + 1);
    expect(within(cardOf('Total TP')).getByText('$ 3.125.400,50')).toBeInTheDocument();
    expect(within(cardOf('Total Gauss')).getByText('$ 14.120.900,10')).toBeInTheDocument();
    expect(within(cardOf('Total TP')).queryByText(/sin costo TP/)).not.toBeInTheDocument();
  });

  it('flags the TP lines without a TP cost with a warning count', () => {
    strip({ ...OFF, total_tp: TP_KPIS });
    const badge = within(cardOf('Total TP')).getByText(/3 sin costo TP/);
    expect(badge).toHaveAttribute('title', '3 ventas de la tienda TP-Link sin costo TP: el Total TP está incompleto');
  });

  it('renders an unknown Total TP as a dash marked incomplete, never as 0', () => {
    strip({ ...OFF, total_tp: { value: null, incompletos: 4 } });
    const card = within(cardOf('Total TP'));
    expect(card.getByText('—')).toBeInTheDocument();
    expect(card.getByText('incompleto')).toBeInTheDocument();
    expect(card.queryByText(/\$ 0,00/)).not.toBeInTheDocument();
  });

  it('says the markup uses the TP cost on TP-store operations', () => {
    strip({ ...OFF, total_tp: TP_KPIS });
    expect(within(cardOf('Markup promedio')).getByText('Usa el costo TP en las operaciones de la tienda TP-Link')).toBeInTheDocument();
  });

  it('never shows the card without the margin permission', () => {
    strip({ ...OFF, total_tp: TP_KPIS }, false);
    expect(screen.queryByText('Total TP')).not.toBeInTheDocument();
  });

  it.each([
    ['complete', { value: 3125400.5, incompletos: 0 }, 'Tienda TP-Link'],
    ['partial', { value: 3125400.5, incompletos: 3 }, null],
    ['incomplete', { value: null, incompletos: 4 }, null],
    ['none', { value: null, incompletos: 0 }, 'Sin ventas de la tienda TP-Link'],
  ])('the Total TP card subtitle for a %s figure', (_kind, tp, subtitle) => {
    strip({ ...OFF, total_tp: tp });
    const card = within(cardOf('Total TP'));
    if (subtitle === 'Tienda TP-Link') {
      expect(card.getByText('Tienda TP-Link')).toBeInTheDocument();
      expect(card.queryByText('Sin ventas de la tienda TP-Link')).not.toBeInTheDocument();
    } else if (subtitle) {
      expect(card.getByText(subtitle)).toBeInTheDocument();
      expect(card.queryByText('Tienda TP-Link')).not.toBeInTheDocument();
      expect(card.queryByText('incompleto')).not.toBeInTheDocument();
    } else {
      // Lines without a TP cost: the warning count takes the subtitle's place.
      expect(card.getByText(/sin costo TP/)).toBeInTheDocument();
      expect(card.queryByText('Tienda TP-Link')).not.toBeInTheDocument();
      expect(card.queryByText('Sin ventas de la tienda TP-Link')).not.toBeInTheDocument();
    }
  });
});


describe('MetricasKpiStrip for a tplink.solo user', () => {
  // The board drops `total_gauss` for this user: the key is absent, not null.
  const { total_gauss: _gauss, ...withoutGauss } = OFF;
  const soloStrip = (tp = TP_KPIS) =>
    render(<MetricasKpiStrip kpis={{ ...withoutGauss, total_tp: tp }} canSeeMargin groupBy="product" tpSolo />);

  it('has no Total Gauss card, and shows Total TP and Markup TP', () => {
    soloStrip();
    expect(screen.queryByText('Total Gauss')).not.toBeInTheDocument();
    expect(within(cardOf('Total TP')).getByText('$ 3.125.400,50')).toBeInTheDocument();
    expect(cardOf('Markup TP')).not.toBeNull();
    expect(screen.queryByText('Markup promedio')).not.toBeInTheDocument();
  });

  it('keeps the incomplete dash and the warning count', () => {
    soloStrip({ value: null, incompletos: 4 });
    const card = within(cardOf('Total TP'));
    expect(card.getByText('—')).toBeInTheDocument();
    expect(card.getByText('incompleto')).toBeInTheDocument();
    expect(card.getByTitle('4 ventas de la tienda TP-Link sin costo TP: el Total TP está incompleto')).toBeInTheDocument();
  });
});
