import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import MetricasKpiStrip from './MetricasKpiStrip';
import { metricasKpiOptions } from './metricasKpiOptions';
import { BOARD_RESPONSE } from '../../test/visual/metricasMlFixtures';

const KPIS = { ...BOARD_RESPONSE.kpis, total_tp: { value: 3125400.5, incompletos: 0 } };
const labels = () => [...document.querySelectorAll('div[class*="label"] > span:first-child')].map((el) => el.textContent);
const ids = (options) => options.map((option) => option.id);

describe('MetricasKpiStrip hideable cards', () => {
  it('renders every card with nothing hidden', () => {
    render(<MetricasKpiStrip kpis={KPIS} canSeeMargin groupBy="product" />);
    expect(labels()).toEqual(metricasKpiOptions(KPIS, { canSeeMargin: true, groupBy: 'product' }).filter((o) => o.id !== 'ads').map((o) => o.label));
  });

  it('lists only the KPIs this viewer sees, conditional ones included (S1, S2)', () => {
    expect(ids(metricasKpiOptions({ ...KPIS, ads: { cost_total: 1 } }, { canSeeMargin: true, groupBy: 'product' }))).toEqual(
      expect.arrayContaining(['total_gauss', 'total_tp', 'markup', 'ads']),
    );
    expect(ids(metricasKpiOptions({ ...KPIS, ads: { cost_total: 1 } }, { canSeeMargin: false, groupBy: 'product' }))).not.toEqual(
      expect.arrayContaining(['total_tp']),
    );
    expect(ids(metricasKpiOptions(KPIS, { canSeeMargin: true, groupBy: 'product' }))).not.toContain('ads');
    expect(ids(metricasKpiOptions(KPIS, { canSeeMargin: true, groupBy: 'product', tpSolo: true }))).not.toContain('total_gauss');
  });

  it('drops a hidden card and sizes the row to the cards left (S5)', () => {
    render(<MetricasKpiStrip kpis={KPIS} canSeeMargin groupBy="product" isVisible={(id) => id !== 'total_tp' && id !== 'units'} />);
    expect(labels()).not.toContain('Total TP');
    expect(labels()).not.toContain('Unidades vendidas');
    const row = screen.getByRole('region', { name: 'Indicadores del período' });
    expect(row.style.getPropertyValue('--kpi-count')).toBe(String(labels().length));
  });

  it('leaves no card row when every card is hidden (S5)', () => {
    render(<MetricasKpiStrip kpis={KPIS} canSeeMargin groupBy="product" isVisible={() => false} />);
    expect(screen.queryByRole('region', { name: 'Indicadores del período' })).not.toBeInTheDocument();
  });
});
