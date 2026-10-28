import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import MetricasKpiStrip from './MetricasKpiStrip';
import { BOARD_RESPONSE } from '../../test/visual/metricasMlFixtures';

const KPIS = {
  ...BOARD_RESPONSE.kpis,
  operations: { value: 1240, delta_pct: 12.5, series: [40, 42] },
  ticket: { value: 43333.33, delta_pct: -3.2, series: [41000, 45000] },
  units_per_sale: { value: 1.75, delta_pct: 2.1 },
};
const cardOf = (label) => screen.getByText(label, { selector: 'span' }).closest('div[class*="card"]');
const strip = (kpis, canSeeMargin = true) => render(<MetricasKpiStrip kpis={kpis} canSeeMargin={canSeeMargin} groupBy="product" />);

describe('MetricasKpiStrip operations (audit B1a)', () => {
  it('shows the operations and the units per sale under the units', () => {
    strip(KPIS);
    expect(within(cardOf('Unidades vendidas')).getByText('1.240 operaciones · 1,75 por venta')).toBeInTheDocument();
  });

  it('shows the average ticket under the gross', () => {
    strip(KPIS);
    const card = within(cardOf('Facturado bruto'));
    expect(card.getByText('Ticket promedio:')).toBeInTheDocument();
    expect(card.getByText('$ 43.333,33')).toBeInTheDocument();
  });

  it('adds no card: the row keeps its cards', () => {
    strip(KPIS);
    expect(screen.queryByText('Operaciones', { selector: 'span' })).not.toBeInTheDocument();
  });

  it('needs no profit permission', () => {
    strip(KPIS, false);
    expect(within(cardOf('Unidades vendidas')).getByText('1.240 operaciones · 1,75 por venta')).toBeInTheDocument();
    expect(within(cardOf('Facturado bruto')).getByText('$ 43.333,33')).toBeInTheDocument();
  });

  it('without operations the ticket and the units per sale are unknown, never 0', () => {
    strip({
      ...KPIS,
      operations: { value: 0, delta_pct: null, series: [0, 0] },
      ticket: { value: null, delta_pct: null, series: [null, null] },
      units_per_sale: { value: null, delta_pct: null },
    });
    expect(within(cardOf('Unidades vendidas')).getByText('0 operaciones')).toBeInTheDocument();
    const gross = within(cardOf('Facturado bruto'));
    expect(gross.getByText('—')).toBeInTheDocument();
    expect(gross.queryByText(/\$ 0,00/)).not.toBeInTheDocument();
  });

  it('a board response without the figures shows neither line', () => {
    strip({ ...KPIS, operations: undefined, ticket: undefined, units_per_sale: undefined });
    expect(screen.queryByText(/operaciones/)).not.toBeInTheDocument();
    expect(screen.queryByText('Ticket promedio:')).not.toBeInTheDocument();
  });
});
