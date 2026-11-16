/**
 * vpf-metricas-canal-fe T2 (S2, C3): "Ventas por día" per channel. Todo stacks ML and Por fuera per day
 * (`kpis.gross.series_por_canal`) with a legend; Por fuera shows every day of the period in millions, its highest
 * and lowest day marked (approved mockup 2); ML keeps its 14 days.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import VentasPorDiaChart from './VentasPorDiaChart';

const PERIOD = { date_from: '2026-10-01', date_to: '2026-10-20' };
const ML = Array.from({ length: 20 }, (_, i) => 1_000_000 + i * 10_000);
const FUERA = Array.from({ length: 20 }, (_, i) => (i % 7 === 3 ? 0 : 2_000_000 + i * 100_000));
const TODO = { gross: { series: ML.map((v, i) => v + FUERA[i]), series_por_canal: { ml: ML, fuera: FUERA } } };

const barras = () => within(screen.getByRole('list', { name: 'Ventas por día' })).getAllByRole('listitem');

describe('VentasPorDiaChart with canal=todo', () => {
  it('stacks ML under Por fuera for each of the last 14 days, with a legend and the total over the bar', () => {
    render(<VentasPorDiaChart period={PERIOD} kpis={TODO} canal="todo" />);

    const legend = screen.getByTestId('ventas-por-dia-leyenda');
    expect(within(legend).getByText('ML')).toBeInTheDocument();
    expect(within(legend).getByText('Por fuera')).toBeInTheDocument();
    const dias = barras();
    expect(dias).toHaveLength(14);
    const last = dias[13];
    expect(last).toHaveAttribute('aria-label', '20/10: $ 5.090.000,00 - ML $ 1.190.000,00 · Por fuera $ 3.900.000,00');
    expect(last.querySelector('[data-canal="ml"]')).not.toBeNull();
    expect(last.querySelector('[data-canal="fuera"]')).not.toBeNull();
    expect(within(last).getByText('5,1 M')).toBeVisible();
    // No highest / lowest marks on the stacked bars.
    expect(dias.filter((d) => d.hasAttribute('data-extremo'))).toHaveLength(0);
  });
});

describe('VentasPorDiaChart with canal=fuera', () => {
  it('shows every day of the period in millions, the day number under each bar', () => {
    render(<VentasPorDiaChart period={PERIOD} kpis={{ gross: { series: FUERA } }} canal="fuera" />);

    expect(screen.getByText(/millones/)).toBeInTheDocument();
    const dias = barras();
    expect(dias).toHaveLength(20);
    expect(within(dias[0]).getByText('01')).toBeInTheDocument();
    expect(within(dias[0]).getByText('2,0')).toBeVisible();
    expect(dias[19]).toHaveAttribute('data-extremo', 'max');
    // A day without sales has no amount over it and is not the lowest day.
    expect(dias[3]).not.toHaveAttribute('data-extremo');
    expect(dias[3]).toHaveAttribute('data-vacio');
    expect(dias[0]).toHaveAttribute('data-extremo', 'min');
  });
});

describe('VentasPorDiaChart with canal=ml (unchanged)', () => {
  it('keeps the last 14 days and the operations, even when the answer has a split', () => {
    render(
      <VentasPorDiaChart
        period={PERIOD}
        kpis={{ ...TODO, operations: { series: Array(20).fill(3) } }}
        canal="ml"
      />,
    );

    expect(barras()).toHaveLength(14);
    expect(within(barras()[0]).getByText('3 ops')).toBeInTheDocument();
    expect(screen.queryByTestId('ventas-por-dia-leyenda')).toBeNull();
  });
});
