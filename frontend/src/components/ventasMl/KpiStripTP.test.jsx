import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import KpiStripTP from './KpiStripTP';

const KPI_TP = {
  groups_count: 3,
  orders_count: 4,
  gross_billed_ars: 3000,
  gross_billed_other: {},
  neto_sum: 2500,
  neto_unknown_count: 0,
  recalculating_count: 1,
  pending_count: 0,
  failed_count: 0,
  excluded_non_money_orders_count: 0,
  excluded_non_money_ars: 0,
  worker_alive: true,
  total_tp_sum: 2433.06,
  tp_incompleto_count: 2,
  markup_tp_weighted_pct: 270.3,
};

describe('KpiStripTP', () => {
  it('shows Total TP, Markup TP and the incomplete count, never a Gauss card', () => {
    render(<KpiStripTP kpi={KPI_TP} loading={false} error={null} />);
    const region = screen.getByRole('region', { name: 'Métricas principales' });
    expect(region).toHaveTextContent('Total TP');
    expect(region).toHaveTextContent('2.433,06');
    expect(region).toHaveTextContent('Markup TP');
    expect(region).toHaveTextContent('270,3%');
    expect(region).toHaveTextContent('TP incompleto');
    // 2 incomplete + 1 recalculating: both lack a usable Total TP.
    expect(screen.getByTestId('tp-incompleto-count')).toHaveTextContent('3');
    expect(region).toHaveTextContent('2 incompletos · 1 recalculando · 0 pendientes · 0 fallidos');
    expect(region).not.toHaveTextContent(/gauss/i);
    // Sale fields stay.
    expect(region).toHaveTextContent('Neto ML');
    expect(region).toHaveTextContent('Facturado bruto');
  });

  it('reads a dash, never 0%, when the TP markup is unknown', () => {
    render(<KpiStripTP kpi={{ ...KPI_TP, markup_tp_weighted_pct: null }} loading={false} error={null} />);
    expect(screen.getByTestId('markup-tp')).toHaveTextContent('—');
  });

  it('keeps the shared loading and error states', () => {
    const { rerender } = render(<KpiStripTP kpi={null} loading error={null} />);
    expect(screen.getByText('Cargando métricas…')).toBeInTheDocument();
    rerender(<KpiStripTP kpi={null} loading={false} error="disabled" />);
    expect(screen.getByText('Las métricas de ventas están desactivadas.')).toBeInTheDocument();
  });
});
