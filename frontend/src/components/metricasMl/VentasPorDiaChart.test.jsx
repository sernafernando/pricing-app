import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import VentasPorDiaChart from './VentasPorDiaChart';

// 20 days from 2026-09-01: the chart keeps the last 14 (09-07 .. 09-20).
const GROSS = [1, 2, 3, 4, 5, 6, 1000, 1200, 900, 1500.5, 800, 300, 1100, 950, 1000, 1000, 1000, 1000, 1000, 1000];
const OPS = [1, 1, 1, 1, 1, 1, 10, 12, 9, 15, 8, 3, 11, 9, 10, 10, 10, 10, 10, 10];
const PERIOD = { date_from: '2026-09-01', date_to: '2026-09-20' };
const kpis = (gross = GROSS, ops = OPS) => ({
  gross: { series: gross },
  ...(ops ? { operations: { series: ops } } : {}),
});

const barras = () => within(screen.getByRole('list', { name: 'Ventas por día' })).getAllByRole('listitem');

describe('VentasPorDiaChart', () => {
  it('shows the last 14 days with their date and operations, oldest first', () => {
    render(<VentasPorDiaChart period={PERIOD} kpis={kpis()} />);

    expect(screen.getByRole('heading', { name: 'Ventas por día' })).toBeInTheDocument();
    const dias = barras();
    expect(dias).toHaveLength(14);
    expect(within(dias[0]).getByText('07/09')).toBeInTheDocument();
    expect(within(dias[0]).getByText('10 ops')).toBeInTheDocument();
    expect(within(dias[13]).getByText('20/09')).toBeInTheDocument();
  });

  it('each bar says its amount and operations on hover', () => {
    render(<VentasPorDiaChart period={PERIOD} kpis={kpis()} />);

    expect(barras()[3]).toHaveAttribute('title', '$ 1.500,50 - 15 ops');
    // Screen readers get it too, not only the mouse (the amount over most bars is hidden).
    expect(screen.getByRole('listitem', { name: '10/09: $ 1.500,50 - 15 ops' })).toBe(barras()[3]);
  });

  it('marks the highest day green and the lowest red, with their amounts always visible', () => {
    render(<VentasPorDiaChart period={PERIOD} kpis={kpis()} />);
    const dias = barras();

    expect(dias[3]).toHaveAttribute('data-extremo', 'max');
    expect(within(dias[3]).getByText('1.501')).toBeVisible(); // whole pesos on the bar; the tooltip keeps the cents
    expect(dias[5]).toHaveAttribute('data-extremo', 'min');
    expect(within(dias[5]).getByText('300')).toBeVisible();
    expect(dias.filter((d) => d.hasAttribute('data-extremo'))).toHaveLength(2);
  });

  it('marks no day when every day sold the same', () => {
    render(<VentasPorDiaChart period={PERIOD} kpis={kpis(Array(14).fill(500), Array(14).fill(2))} />);

    expect(barras().filter((d) => d.hasAttribute('data-extremo'))).toHaveLength(0);
  });

  it('a day without operations data says only its amount', () => {
    render(<VentasPorDiaChart period={PERIOD} kpis={kpis(GROSS, null)} />);
    const [primero] = barras();

    expect(primero).toHaveAttribute('title', '$ 1.000,00');
    expect(within(primero).queryByText(/ops$/)).toBeNull();
  });

  it('shows nothing without a daily series', () => {
    const { container } = render(<VentasPorDiaChart period={PERIOD} kpis={{ gross: { series: [] } }} />);

    expect(container).toBeEmptyDOMElement();
  });
});
