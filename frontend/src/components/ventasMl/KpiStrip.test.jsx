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

  it('breaks the incomplete card down by state, without a total over overlapping counts', () => {
    // This test used to assert 2+4+3+1+0 = 10, which CODIFIED the double
    // count: `neto_unknown_count` (2) and `total_gauss_unresolved_count` (4)
    // can describe the same order, so no sum over them is true. The headline
    // is now only the three mutually exclusive states — 3 recalculating +
    // 1 pending + 0 failed = 4 — and the overlapping pair is reported apart.
    render(<KpiStrip kpi={FULL_KPI} loading={false} error={null} />);
    const label = screen.getByText(/desglose incompleto/i);
    const card = label.closest('div');
    expect(within(card).getByText('4')).toBeInTheDocument();
    expect(within(card).queryByText('10')).not.toBeInTheDocument();
    expect(within(card).getByText(/2 sin neto/i)).toBeInTheDocument();
    expect(within(card).getByText(/4 sin Total Gauss/i)).toBeInTheDocument();
  });

  it('warns when the metrics worker is not alive', () => {
    render(<KpiStrip kpi={{ ...FULL_KPI, worker_alive: false }} loading={false} error={null} />);
    expect(screen.getByText(/recálculo detenido|worker.*(caído|inactivo)/i)).toBeInTheDocument();
  });
});

describe('the "Desglose incompleto" card never invents a total', () => {
  // One order can be BOTH `neto is None` AND `gauss_status == 'unresolved'`:
  // `aggregate.py` increments `neto_unknown_count` and
  // `total_gauss_unresolved_count` from the SAME stored row, independently.
  // Adding them reports that one order as two — and since an unresolved Gauss
  // usually means an unknown neto too, the card would roughly DOUBLE the real
  // number. On a screen whose whole reason to exist is that the totals stop
  // lying, a headline built from that sum is the worst possible cell.
  //
  // `recalculating`/`pending`/`failed` DO come from `metrics_state` and are
  // mutually exclusive with each other and with the stored-row counters (such
  // an order never reaches the row block at all — `aggregate.py` `continue`s),
  // so those three are the only ones that can honestly be added together.
  it('does not render the sum of neto_unknown and total_gauss_unresolved', () => {
    render(
      <KpiStrip
        kpi={({ ...FULL_KPI, 
          neto_unknown_count: 7,
          total_gauss_unresolved_count: 7,
          recalculating_count: 0,
          pending_count: 0,
          failed_count: 0,
        })}
        loading={false}
        error={null}
      />
    );

    // 7 + 7 = 14 would be the double-counted headline.
    expect(screen.queryByText('14')).not.toBeInTheDocument();
    // Each figure is still reported, on its own terms.
    expect(screen.getByText(/7 sin neto/)).toBeInTheDocument();
    expect(screen.getByText(/7 sin Total Gauss/)).toBeInTheDocument();
  });

  it('adds up only the three states that are mutually exclusive', () => {
    render(
      <KpiStrip
        kpi={({ ...FULL_KPI, 
          neto_unknown_count: 0,
          total_gauss_unresolved_count: 0,
          recalculating_count: 2,
          pending_count: 3,
          failed_count: 1,
        })}
        loading={false}
        error={null}
      />
    );

    expect(screen.getByText('6')).toBeInTheDocument();
  });
});
