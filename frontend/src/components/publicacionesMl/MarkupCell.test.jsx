/**
 * MarkupCell (publicaciones-ml-vista P11b.T1): the markup of a publication as
 * the backend computed it (P6) -- a range over its variations, one number when
 * they agree, "—" with the reason when it cannot be computed, "(parcial)" when
 * some variations have no cost. The screen never computes a markup itself.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import MarkupCell from './MarkupCell';
import { buildColumns } from './columns';

const markup = (overrides) => ({ min: 12, max: 18, worst: 12, any_negative: false, reason: 'ok', partial: 0, ads: null, ...overrides });

describe('MarkupCell', () => {
  it('shows the range "12,0% – 18,0%" when the variations differ', () => {
    render(<MarkupCell markup={markup()} />);
    expect(screen.getByText('12,0% – 18,0%')).toBeInTheDocument();
  });

  it('shows a single value when every variation has the same markup', () => {
    render(<MarkupCell markup={markup({ min: 15, max: 15, worst: 15 })} />);
    expect(screen.getByText('15,0%')).toBeInTheDocument();
    expect(screen.queryByText(/–/)).not.toBeInTheDocument();
  });

  it('keeps a real 0% as 0%, never as "—"', () => {
    render(<MarkupCell markup={markup({ min: 0, max: 0, worst: 0 })} />);
    expect(screen.getByText('0,0%')).toBeInTheDocument();
  });

  it('flags a publication with a negative variation', () => {
    render(<MarkupCell markup={markup({ min: -3.5, max: 8, worst: -3.5, any_negative: true })} />);
    expect(screen.getByText('-3,5% – 8,0%')).toHaveAttribute('data-negative');
  });

  it('does not flag a publication without negative variations', () => {
    render(<MarkupCell markup={markup()} />);
    expect(screen.getByText('12,0% – 18,0%')).not.toHaveAttribute('data-negative');
  });

  it('adds "(parcial)" when some variations could not be priced, and says how many', () => {
    render(<MarkupCell markup={markup({ partial: 2 })} />);
    const partial = screen.getByText('(parcial)');
    expect(partial).toHaveAttribute('title', '2 variaciones sin costo no entran en el rango');
    expect(screen.getByText('12,0% – 18,0%')).toBeInTheDocument();
  });

  it('says "1 variación" in the singular', () => {
    render(<MarkupCell markup={markup({ partial: 1 })} />);
    expect(screen.getByText('(parcial)')).toHaveAttribute('title', '1 variación sin costo no entra en el rango');
  });

  it.each([
    ['sin_vinculo', 'La publicación no está vinculada a un producto'],
    ['sin_costo', 'El producto vinculado no tiene costo'],
    ['sin_comision', 'No hay comisión para la lista de precios de la publicación'],
    ['sin_precio', 'La publicación no tiene precio'],
    ['ads_sin_ventas', 'Hay costo de Ads pero no hubo unidades vendidas'],
  ])('renders "—" with the reason as tooltip for %s', (reason, text) => {
    render(<MarkupCell markup={markup({ min: null, max: null, worst: null, reason })} />);
    expect(screen.getByText('—')).toHaveAttribute('title', text);
  });

  it('gives a generic tooltip to a reason it does not know', () => {
    render(<MarkupCell markup={markup({ min: null, max: null, worst: null, reason: 'algo_nuevo' })} />);
    expect(screen.getByText('—')).toHaveAttribute('title', 'No se pudo calcular el markup');
  });

  it('renders "—" without a tooltip when the row has no markup block at all', () => {
    render(<MarkupCell markup={undefined} />);
    expect(screen.getByText('—')).not.toHaveAttribute('title');
  });
});

describe('the markup column', () => {
  const keys = (options) => buildColumns({ eventsEnabled: true, ...options }).map((column) => column.key);

  it('does not exist without ml_metricas.ver_ganancia', () => {
    expect(keys({ canSeeMargin: false })).not.toContain('markup');
    expect(keys({})).not.toContain('markup');
  });

  it('exists with ver_ganancia, sortable, right after the price', () => {
    const columns = buildColumns({ eventsEnabled: true, canSeeMargin: true });
    expect(columns.map((column) => column.key).indexOf('markup')).toBe(columns.map((column) => column.key).indexOf('precio') + 1);
    expect(columns.find((column) => column.key === 'markup').sortable).toBe(true);
  });
});
