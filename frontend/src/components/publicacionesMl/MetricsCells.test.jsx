/**
 * The Métricas ML figures of a publication (`row.metrics`, the Board's own
 * publication row over the last 30 days), rendered as the Métricas screen
 * renders them, and the three stock figures, each from its own source and
 * never summed. A publication Métricas has no row for reads "—".
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  AgeingCell,
  FullStockCell,
  GrossCell,
  LastSaleCell,
  MarkupRealCell,
  MarkupTrendCell,
  OwnStockCell,
  TotalGaussCell,
  UnitsCell,
  UnitsTrendCell,
} from './MetricsCells';

const SERIES_UNITS = Array.from({ length: 90 }, (_, i) => (i >= 83 ? 2 : 0));
const SERIES_MARKUP = Array.from({ length: 90 }, (_, i) => (i === 89 ? 18.5 : null));
const METRICS = {
  units_7d: 14,
  units_30d: 1234,
  series_units_90d: SERIES_UNITS,
  gross_30d: 98500.5,
  last_sale_at: '2026-10-14T13:05:00Z',
  ageing_days: 45,
  total_gauss_30d: -1500,
  markup_30d: 18.5,
  markup_delta_pp: -2.1,
  series_markup_90d: SERIES_MARKUP,
};
const NO_SALES = { ...METRICS, units_7d: 0, units_30d: 0, gross_30d: 0, total_gauss_30d: 0, markup_30d: null };

describe('units', () => {
  it('shows the 7 and 30-day units as Métricas formats them', () => {
    render(
      <>
        <UnitsCell value={METRICS.units_7d} />
        <UnitsCell value={METRICS.units_30d} strong />
      </>,
    );
    expect(screen.getByText('14')).toBeInTheDocument();
    expect(screen.getByText('1.234')).toBeInTheDocument();
  });

  it('a counted zero reads 0; no Métricas row reads "—"', () => {
    const { rerender } = render(<UnitsCell value={0} />);
    expect(screen.getByText('0')).toBeInTheDocument();
    rerender(<UnitsCell value={undefined} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('draws the weekly units of the 90 days, toned by the last week against the one before', () => {
    render(<UnitsTrendCell metrics={METRICS} />);
    const spark = screen.getByRole('img', { name: 'Unidades por semana, 90 días' });
    expect(spark).toHaveAttribute('data-tone', 'up');
  });

  it('has no trend without a Métricas row', () => {
    render(<UnitsTrendCell metrics={null} />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('markup', () => {
  it('shows the real 30-day markup with its tone', () => {
    render(<MarkupRealCell metrics={METRICS} />);
    expect(screen.getByText('18,5%')).toHaveAttribute('data-tone', 'good');
  });

  it('reads "—" without sales, without cost or without a row', () => {
    const { rerender } = render(<MarkupRealCell metrics={NO_SALES} />);
    expect(screen.getByText('—')).toBeInTheDocument();
    rerender(<MarkupRealCell metrics={null} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('draws the daily markup of the 90 days, toned by the change against the previous 30 days', () => {
    render(<MarkupTrendCell metrics={METRICS} />);
    expect(screen.getByRole('img', { name: 'Markup diario, 90 días' })).toHaveAttribute('data-tone', 'down');
  });
});

describe('result', () => {
  it('shows the gross revenue and Total Gauss as money, the loss in its tone', () => {
    render(
      <>
        <GrossCell metrics={METRICS} />
        <TotalGaussCell metrics={METRICS} />
      </>,
    );
    expect(screen.getByText('$ 98.500,50')).toBeInTheDocument();
    expect(screen.getByText('-$ 1.500,00')).toHaveAttribute('data-tone', 'negative');
  });

  it('reads "—" when the publication did not sell in the 30 days', () => {
    render(
      <>
        <GrossCell metrics={NO_SALES} />
        <TotalGaussCell metrics={null} />
      </>,
    );
    expect(screen.getAllByText('—')).toHaveLength(2);
  });
});

describe('rotation', () => {
  it('shows the last sale and how long ago', () => {
    render(<LastSaleCell metrics={METRICS} now={new Date('2026-10-16T15:00:00Z')} />);
    expect(screen.getByText('14/10 10:05')).toBeInTheDocument();
    expect(screen.getByText('hace 2 días')).toBeInTheDocument();
  });

  it('shows the ageing as a chip toned like Métricas', () => {
    render(<AgeingCell metrics={METRICS} />);
    expect(screen.getByText('45 d')).toHaveAttribute('data-tone', 'low');
  });

  it('reads "—" without a Métricas row', () => {
    render(
      <>
        <LastSaleCell metrics={null} />
        <AgeingCell metrics={null} />
      </>,
    );
    expect(screen.getAllByText('—')).toHaveLength(2);
  });
});

describe('stock, never summed', () => {
  const STOCK = { available: 34, full: 20, own: 14 };

  it('shows our own stock and the Full stock each on its own, never the available sum', () => {
    render(
      <>
        <OwnStockCell stock={STOCK} />
        <FullStockCell stock={STOCK} />
      </>,
    );
    expect(screen.getByText('14')).toBeInTheDocument();
    expect(screen.getByText('20')).toBeInTheDocument();
    expect(screen.queryByText('34')).not.toBeInTheDocument();
  });

  it('flags a real zero and reads "—" when the figure is unknown', () => {
    render(
      <>
        <OwnStockCell stock={{ available: 5, full: 5, own: 0 }} />
        <FullStockCell stock={{ available: 5, full: null, own: 5 }} />
      </>,
    );
    expect(screen.getByText('0')).toHaveAttribute('data-out');
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
