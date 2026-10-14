/**
 * The 30-day sales summary of a publication (`row.sales_30d`, from Métricas
 * ML's base): units and gross revenue with `ml_metricas.ver`, the real markup
 * also with `ml_metricas.ver_ganancia`. No sales is "—", never 0.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Markup30dCell, Sales30dCell } from './SalesCells';
import { buildColumns, columnChoicesOver, defaultColumnVisibility } from './columns';

describe('Sales30dCell', () => {
  it('shows the units and the gross revenue', () => {
    render(<Sales30dCell sales={{ units: 1234, gross: 98500.5 }} />);
    expect(screen.getByText('1.234 u.')).toBeInTheDocument();
    expect(screen.getByText('98.500,50')).toBeInTheDocument();
  });

  it('renders "—" when the publication did not sell', () => {
    render(<Sales30dCell sales={{ units: 0, gross: 0 }} />);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText(/u\./)).not.toBeInTheDocument();
  });

  it('renders "—" when the row has no sales block', () => {
    render(<Sales30dCell sales={undefined} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('Markup30dCell', () => {
  it('shows the real markup with one decimal', () => {
    render(<Markup30dCell sales={{ units: 5, gross: 50, markup: 15 }} />);
    expect(screen.getByText('15,0%')).toBeInTheDocument();
  });

  it('flags a negative markup', () => {
    render(<Markup30dCell sales={{ units: 5, gross: 50, markup: -2.5 }} />);
    expect(screen.getByText('-2,5%')).toHaveAttribute('data-negative');
  });

  it('keeps a real 0% as 0%', () => {
    render(<Markup30dCell sales={{ units: 5, gross: 50, markup: 0 }} />);
    expect(screen.getByText('0,0%')).toBeInTheDocument();
  });

  it('renders "—" without sales or without cost', () => {
    const { rerender } = render(<Markup30dCell sales={{ units: 0, gross: 0, markup: null }} />);
    expect(screen.getByText('—')).toBeInTheDocument();
    rerender(<Markup30dCell sales={undefined} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('the 30-day columns', () => {
  const keys = (options) => buildColumns({ eventsEnabled: false, ...options }).map((column) => column.key);

  it('do not exist without ml_metricas.ver', () => {
    expect(keys({ canSeeMargin: true })).not.toContain('ventas_30d');
    expect(keys({ canSeeMargin: true })).not.toContain('markup_30d');
  });

  it('show sales with ml_metricas.ver, and the markup only with ver_ganancia too', () => {
    expect(keys({ canSeeSales: true })).toContain('ventas_30d');
    expect(keys({ canSeeSales: true })).not.toContain('markup_30d');
    expect(keys({ canSeeSales: true, canSeeMargin: true })).toEqual(expect.arrayContaining(['ventas_30d', 'markup_30d']));
  });

  it('are named "Ventas 30d" and "Markup 30d"', () => {
    const columns = buildColumns({ eventsEnabled: false, canSeeSales: true, canSeeMargin: true });
    expect(columns.find((column) => column.key === 'ventas_30d').header).toBe('Ventas 30d');
    expect(columns.find((column) => column.key === 'markup_30d').header).toBe('Markup 30d');
  });

  it('replace the worst-variation markup by default, which stays in the picker', () => {
    expect(defaultColumnVisibility({ canSeeSales: true, canSeeMargin: true })).toEqual({ markup: false });
    expect(keys({ canSeeSales: true, canSeeMargin: true })).toContain('markup');
  });

  it('keep the worst-variation markup visible when Markup 30d is not shown', () => {
    expect(defaultColumnVisibility({ canSeeSales: false, canSeeMargin: true })).toEqual({});
    expect(defaultColumnVisibility({ canSeeSales: true, canSeeMargin: false })).toEqual({});
  });

  it('keep only what the user changed from the default, so the default can follow permissions', () => {
    const defaults = { markup: false };
    expect(columnChoicesOver({ markup: false, stock_full: false }, defaults)).toEqual({ stock_full: false });
    expect(columnChoicesOver({ markup: true }, defaults)).toEqual({ markup: true });
    expect(columnChoicesOver({ markup: false, stock_full: true }, {})).toEqual({ markup: false });
  });
});
