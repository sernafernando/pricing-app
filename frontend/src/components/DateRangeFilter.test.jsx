/**
 * Tests for DateRangeFilter.jsx (feat/ventas-ml-filtro-fechas).
 *
 * Scope:
 *  - Each preset produces the exact window DashboardMetricasML.jsx produced
 *    before the extraction, against a frozen clock -- this is the whole
 *    point of "el mismo módulo".
 *  - The custom range only applies on "Aplicar", never while typing.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import DateRangeFilter, { calcularRangoPreset } from './DateRangeFilter';

// Frozen "hoy": Thursday 2026-09-17 (a Thursday, so 'mesActual' and month
// arithmetic aren't accidentally coincidental with day-of-month edge cases).
const HOY = new Date(2026, 8, 17); // months are 0-indexed: September

describe('calcularRangoPreset', () => {
  it('hoy: desde == hasta == today', () => {
    expect(calcularRangoPreset('hoy', HOY)).toEqual({ desde: '2026-09-17', hasta: '2026-09-17' });
  });

  it('ayer: desde == hasta == yesterday', () => {
    expect(calcularRangoPreset('ayer', HOY)).toEqual({ desde: '2026-09-16', hasta: '2026-09-16' });
  });

  it('3d: desde = hoy - 2 (a 3-day window inclusive)', () => {
    expect(calcularRangoPreset('3d', HOY)).toEqual({ desde: '2026-09-15', hasta: '2026-09-17' });
  });

  it('7d: desde = hoy - 6, NOT hoy - 7', () => {
    expect(calcularRangoPreset('7d', HOY)).toEqual({ desde: '2026-09-11', hasta: '2026-09-17' });
  });

  it('14d: desde = hoy - 13', () => {
    expect(calcularRangoPreset('14d', HOY)).toEqual({ desde: '2026-09-04', hasta: '2026-09-17' });
  });

  it('mesActual: desde = first day of current month', () => {
    expect(calcularRangoPreset('mesActual', HOY)).toEqual({ desde: '2026-09-01', hasta: '2026-09-17' });
  });

  it('30d: desde = hoy - 29', () => {
    expect(calcularRangoPreset('30d', HOY)).toEqual({ desde: '2026-08-19', hasta: '2026-09-17' });
  });

  it('3m: desde = hoy with month - 3', () => {
    expect(calcularRangoPreset('3m', HOY)).toEqual({ desde: '2026-06-17', hasta: '2026-09-17' });
  });

  it('unknown preset returns null', () => {
    expect(calcularRangoPreset('nope', HOY)).toBeNull();
  });
});

describe('DateRangeFilter', () => {
  let onChange;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(HOY);
    onChange = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function renderFilter(props = {}) {
    return render(
      <DateRangeFilter fechaDesde="2026-09-01" fechaHasta="2026-09-17" filtroActivo="mesActual" onChange={onChange} {...props} />
    );
  }

  it('clicking a preset calls onChange with the exact computed window and the preset key', () => {
    renderFilter();
    fireEvent.click(screen.getByText('7d'));
    expect(onChange).toHaveBeenCalledWith({ desde: '2026-09-11', hasta: '2026-09-17', filtro: '7d' });
  });

  it('custom range: typing new dates does NOT call onChange until Aplicar is clicked', () => {
    renderFilter();
    fireEvent.click(screen.getByTitle('Seleccionar rango personalizado'));

    // By LABEL, not by position: `querySelectorAll(...)[0]` silently
    // follows whatever order the markup happens to have, so swapping the
    // two fields would leave this green while the screen lied.
    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-01-01' } });
    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-01-31' } });

    // Typing alone must not trigger onChange.
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText('Aplicar'));

    expect(onChange).toHaveBeenCalledWith({ desde: '2026-01-01', hasta: '2026-01-31', filtro: 'custom' });
  });

  it('refuses an inverted range instead of applying one that matches nothing', () => {
    // A range whose end precedes its start matches NOTHING, and the screen
    // would read "no hay ventas" -- indistinguishable from a real empty
    // result. Refusing keeps the previous range and says why.
    renderFilter();
    fireEvent.click(screen.getByTitle('Seleccionar rango personalizado'));

    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-01-31' } });
    fireEvent.change(screen.getByLabelText('Hasta'), { target: { value: '2026-01-01' } });

    expect(screen.getByRole('alert')).toHaveTextContent(/posterior/i);

    fireEvent.click(screen.getByText('Aplicar'));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('does nothing when Aplicar is pressed with the range still blank', () => {
    // An empty range is not "no filter", it is a filter that says nothing.
    // Applying it marks the control active while CLEARING whatever the
    // page had -- in VentasML, the month filter, since the two are the
    // same axis. The operator would lose their filter by pressing a button
    // that looks like it does nothing.
    // Rendered with NO range: the harness's default seeds both dates, so
    // reusing it would never produce the blank dropdown this case is about.
    renderFilter({ fechaDesde: '', fechaHasta: '', filtroActivo: null });
    fireEvent.click(screen.getByTitle('Seleccionar rango personalizado'));

    fireEvent.click(screen.getByText('Aplicar'));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('does nothing when only one of the two dates is filled', () => {
    renderFilter({ fechaDesde: '', fechaHasta: '', filtroActivo: null });
    fireEvent.click(screen.getByTitle('Seleccionar rango personalizado'));

    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-01-01' } });

    fireEvent.click(screen.getByText('Aplicar'));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('3m clamps instead of rolling into the next month', () => {
    // `setMonth(-3)` on 31 May asks for 31 February, which JavaScript
    // normalises to 3 March -- "últimos 3 meses" starting in the WRONG
    // month, two days late, on every 31st. Métricas carried that bug;
    // sharing this module fixes it on both screens at once.
    vi.setSystemTime(new Date(2026, 4, 31, 12, 0, 0)); // 31 May 2026
    const rango = calcularRangoPreset('3m');
    expect(rango.hasta).toBe('2026-05-31');
    expect(rango.desde).toBe('2026-02-28');
  });

  it('3m keeps the day of month when the target month is long enough', () => {
    vi.setSystemTime(new Date(2026, 5, 15, 12, 0, 0)); // 15 June 2026
    expect(calcularRangoPreset('3m').desde).toBe('2026-03-15');
  });

  it('3m clamps to 29 February in a leap year', () => {
    vi.setSystemTime(new Date(2028, 4, 31, 12, 0, 0)); // 31 May 2028
    expect(calcularRangoPreset('3m').desde).toBe('2028-02-29');
  });
});
