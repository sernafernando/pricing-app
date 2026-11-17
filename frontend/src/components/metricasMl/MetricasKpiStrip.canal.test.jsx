/**
 * vpf-metricas-canal-fe T2 (S2, S6, S10, C3): the KPI cards per channel. Todo splits each card into ML and Por
 * fuera (`kpis.por_canal`); Por fuera reads its documents, the Venta WITH VAT, the other cost and the sin producto
 * lines (`kpis.fuera`); ML keeps the cards it always had.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import MetricasKpiStrip from './MetricasKpiStrip';
import { BOARD_RESPONSE } from '../../test/visual/metricasMlFixtures';
import { FUERA_BOARD_RESPONSE, TODO_BOARD_RESPONSE } from '../../test/visual/metricasMlCanalFixtures';

const cardOf = (label) => screen.getByText(label, { selector: 'span' }).closest('div[class*="card"]');
const strip = (kpis, { canal, costo = 'costo_d', canSeeMargin = true } = {}) =>
  render(<MetricasKpiStrip kpis={kpis} canSeeMargin={canSeeMargin} groupBy="product" canal={canal} costo={costo} />);
const splitLine = (card, label) => within(card).getByText(label, { selector: '[data-split] > span:first-child' }).parentElement;

describe('MetricasKpiStrip with canal=todo', () => {
  it('splits units, gross, Total Gauss and markup into ML and Por fuera', () => {
    strip(TODO_BOARD_RESPONSE.kpis, { canal: 'todo' });

    const units = cardOf('Unidades vendidas');
    expect(splitLine(units, 'ML')).toHaveTextContent('3.412');
    expect(splitLine(units, 'Por fuera')).toHaveTextContent('1.240');
    const gross = cardOf('Facturado bruto');
    expect(splitLine(gross, 'ML')).toHaveTextContent('$ 84.920.450,00');
    expect(splitLine(gross, 'Por fuera')).toHaveTextContent('$ 148.520.300,50');
    const tg = cardOf('Total Gauss');
    expect(splitLine(tg, 'ML')).toHaveTextContent('$ 14.120.900,10');
    expect(splitLine(tg, 'Por fuera')).toHaveTextContent('$ 24.310.000,00');
    expect(within(tg).getByText('ML neto de comisión y envío')).toBeInTheDocument();
    const markup = cardOf('Markup promedio');
    expect(splitLine(markup, 'ML')).toHaveTextContent('21,6%');
    expect(splitLine(markup, 'Por fuera (Costo D)')).toHaveTextContent('19,8%');
  });

  it('without the profit view the margin cards stay locked, the split units and gross stay', () => {
    strip(TODO_BOARD_RESPONSE.kpis, { canal: 'todo', canSeeMargin: false });

    expect(splitLine(cardOf('Unidades vendidas'), 'Por fuera')).toHaveTextContent('1.240');
    expect(within(cardOf('Total Gauss')).getByText('Sin permiso para ver ganancia')).toBeInTheDocument();
    expect(within(cardOf('Total Gauss')).queryByText('$ 24.310.000,00')).not.toBeInTheDocument();
  });
});

describe('MetricasKpiStrip with canal=fuera', () => {
  it('counts the documents and their types under the units', () => {
    strip(FUERA_BOARD_RESPONSE.kpis, { canal: 'fuera' });

    const units = within(cardOf('Unidades vendidas'));
    expect(units.getByText('152 comprobantes')).toBeInTheDocument();
    expect(units.getByText('96 Fc A · 48 Fc B · 6 Nc A · 2 Nd A')).toBeInTheDocument();
  });

  it('says the Venta carries VAT (S10), never "sin IVA", and leaves the cheque surcharge out', () => {
    strip(FUERA_BOARD_RESPONSE.kpis, { canal: 'fuera' });

    const gross = within(cardOf('Facturado'));
    expect(gross.getByText('$ 148.520.300,50')).toBeInTheDocument();
    expect(gross.getByText('con IVA · sin recargo cheque')).toBeInTheDocument();
    expect(screen.queryByText(/sin IVA/)).not.toBeInTheDocument();
  });

  it('shows Total Gauss and markup with the chosen cost and the other cost below', () => {
    strip(FUERA_BOARD_RESPONSE.kpis, { canal: 'fuera' });

    const tg = within(cardOf('Total Gauss'));
    expect(tg.getByText('$ 24.310.000,00')).toBeInTheDocument();
    expect(tg.getByText('venta − Costo D')).toBeInTheDocument();
    expect(tg.getByText('con Costo:').parentElement).toHaveTextContent('con Costo: $ 31.850.000,00');
    const markup = within(cardOf('Markup promedio'));
    expect(markup.getByText('con Costo D')).toBeInTheDocument();
    expect(markup.getByText('con Costo:').parentElement).toHaveTextContent('con Costo: 27,4%');
  });

  it('with costo=costo the alternate is Costo D', () => {
    const kpis = {
      ...FUERA_BOARD_RESPONSE.kpis,
      fuera: { ...FUERA_BOARD_RESPONSE.kpis.fuera, otro_costo: { costo: 'costo_d', margin: 20000000, markup_pct: 15.1 } },
    };
    strip(kpis, { canal: 'fuera', costo: 'costo' });

    const tg = within(cardOf('Total Gauss'));
    expect(tg.getByText('venta − Costo')).toBeInTheDocument();
    expect(tg.getByText('con Costo D:').parentElement).toHaveTextContent('con Costo D: $ 20.000.000,00');
  });

  it('adds the sin producto lines to the products with sales', () => {
    strip(FUERA_BOARD_RESPONSE.kpis, { canal: 'fuera' });

    expect(within(cardOf('Productos con ventas')).getByText(/líneas sin producto/).parentElement).toHaveTextContent(
      '+ 12 líneas sin producto: $ 6.120.400,10',
    );
  });

  it('without ventas_fuera.ver_ganancia (S6) no margin figure shows, not even the other cost', () => {
    strip(
      { ...FUERA_BOARD_RESPONSE.kpis, fuera: { ...FUERA_BOARD_RESPONSE.kpis.fuera, otro_costo: { costo: 'costo', margin: null, markup_pct: null } } },
      { canal: 'fuera', canSeeMargin: false },
    );

    expect(within(cardOf('Total Gauss')).getByText('Sin permiso para ver ganancia')).toBeInTheDocument();
    expect(screen.queryByText('con Costo:')).not.toBeInTheDocument();
  });
});

describe('MetricasKpiStrip with canal=ml (unchanged)', () => {
  it('keeps "Facturado bruto", its sparkline and no channel split even if the answer had one', () => {
    strip({ ...BOARD_RESPONSE.kpis, por_canal: TODO_BOARD_RESPONSE.kpis.por_canal }, { canal: 'ml' });

    expect(cardOf('Facturado bruto')).toBeInTheDocument();
    expect(within(cardOf('Facturado bruto')).getByRole('img', { name: 'Facturado por día' })).toBeInTheDocument();
    expect(document.querySelector('[data-split]')).toBeNull();
  });
});
