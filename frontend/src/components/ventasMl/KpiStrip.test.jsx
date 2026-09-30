/**
 * ventas-ml-kpi-strip T1/T2/T3/T6: the six-card totals strip fed by
 * `GET /ml-ventas-ops/sales/kpis`. Behaviour and text only — this
 * project's Vitest config runs with `css: false`, so layout/computed
 * style assertions are meaningless here (task doc, "TDD IS MANDATORY").
 *
 * HONESTY OF NUMBERS IS THE POINT: an unresolved `markup_weighted_pct`
 * must render as "—", never as 0%; `gross_billed_other` currencies must
 * never be folded into the ARS figure.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import KpiStrip from './KpiStrip';

const FULL_KPI = {
  groups_count: 1284,
  orders_count: 1400,
  gross_billed_ars: 84920450,
  gross_billed_other: { USD: 320.5 },
  neto_sum: 68345120.5,
  neto_unknown_count: 2,
  total_gauss_sum: 54120900.1,
  total_gauss_ok_count: 1200,
  total_gauss_provisional_count: 10,
  total_gauss_unresolved_count: 4,
  markup_weighted_pct: 26.3,
  recalculating_count: 3,
  pending_count: 1,
  failed_count: 0,
  markup_skipped_count: 2,
  worker_alive: true,
  excluded_by_toggle: { a_revisar: 0, en_disputa: 0, mixta: 0, provisorio: 0 },
  effective_switches: {
    include_unknown: true,
    include_in_dispute: true,
    include_mixed: true,
    include_provisional: true,
  },
};

describe('KpiStrip', () => {
  it('shows a loading state instead of stale or zeroed cards', () => {
    render(<KpiStrip kpi={null} loading error={null} />);
    expect(screen.getByText(/cargando/i)).toBeInTheDocument();
  });

  it('shows an error state and no numbers when the request failed', () => {
    render(<KpiStrip kpi={null} loading={false} error="generic" />);
    expect(screen.getByText(/no se pudieron cargar/i)).toBeInTheDocument();
    expect(screen.queryByText('1.284')).not.toBeInTheDocument();
  });

  it('renders the six cards with the totals from the response', () => {
    render(<KpiStrip kpi={FULL_KPI} loading={false} error={null} />);
    expect(screen.getByText('1.284')).toBeInTheDocument(); // Ventas (groups_count)
    expect(screen.getByText(/84\.920\.450,00/)).toBeInTheDocument(); // Facturado bruto
    expect(screen.getByText(/68\.345\.120,50/)).toBeInTheDocument(); // Neto ML
    expect(screen.getByText(/54\.120\.900,10/)).toBeInTheDocument(); // Total Gauss
    expect(screen.getByText(/26,3\s*%/)).toBeInTheDocument(); // Markup promedio
  });

  it('renders a null markup_weighted_pct as an em dash, never as 0%', () => {
    render(<KpiStrip kpi={{ ...FULL_KPI, markup_weighted_pct: null }} loading={false} error={null} />);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText(/0\s*%/)).not.toBeInTheDocument();
  });

  it('never folds gross_billed_other currencies into the ARS figure', () => {
    render(<KpiStrip kpi={FULL_KPI} loading={false} error={null} />);
    // The ARS card shows exactly the ARS amount, not ARS + 320.5 USD.
    expect(screen.getByText(/84\.920\.450,00/)).toBeInTheDocument();
    // The other currency is surfaced separately (not silently dropped).
    expect(screen.getByText(/320,50\s*USD/)).toBeInTheDocument();
  });

  it('rolls up unresolved figures into an incomplete-breakdown card, worded from what it is made of', () => {
    render(<KpiStrip kpi={FULL_KPI} loading={false} error={null} />);
    const label = screen.getByText(/desglose incompleto/i);
    const card = label.closest('div');
    // 2 (neto_unknown) + 4 (total_gauss_unresolved) + 3 (recalculating) + 1 (pending) + 0 (failed) = 10
    expect(within(card).getByText('10')).toBeInTheDocument();
    expect(within(card).getByText(/2.*neto desconocido/i)).toBeInTheDocument();
  });

  it('warns when the metrics worker is not alive', () => {
    render(<KpiStrip kpi={{ ...FULL_KPI, worker_alive: false }} loading={false} error={null} />);
    expect(screen.getByText(/recálculo detenido|worker.*(caído|inactivo)/i)).toBeInTheDocument();
  });
});
