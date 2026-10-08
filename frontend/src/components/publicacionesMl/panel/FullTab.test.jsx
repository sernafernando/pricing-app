/**
 * Full tab (publicaciones-ml-vista P13a.T3): stock in Full and Propio, and the
 * replenishment report (sales 7/14/21/30 days, GMV, days out of stock). A
 * partial report is badged; a flag that is off says why instead of showing
 * invented zeros.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import FullTab from './FullTab';
import { readDetail } from './detailModel';
import { DATA_STATE_OK, DETAIL_RESPONSE, ITEMS, REPLENISHMENT_OK, makeDetail } from '../../../test/visual/publicacionesMlFixtures';

const renderTab = (raw = DETAIL_RESPONSE, dataState = DATA_STATE_OK) => {
  const detail = readDetail(raw);
  return render(<FullTab detail={detail} itemId={detail.itemId} canSeeMargin={false} dataState={dataState} />);
};
const section = (name) => screen.getByRole('region', { name });
const valueOf = (name, label) => within(section(name)).getByText(label, { selector: 'dt' }).nextElementSibling;
const withReplenishment = (overrides) => makeDetail({ replenishment: { ...REPLENISHMENT_OK, ...overrides } });

describe('stock', () => {
  it('shows Full and Propio and when they were read', () => {
    renderTab();
    expect(valueOf('Stock', 'Full')).toHaveTextContent('20');
    expect(valueOf('Stock', 'Propio')).toHaveTextContent('14');
    expect(valueOf('Stock', 'Actualizado').textContent).toMatch(/\d{2}\/\d{2}\/\d{4}/);
  });
});

describe('the replenishment report', () => {
  it('shows the units sold in Full over 7, 14, 21 and 30 days', () => {
    renderTab();
    expect(valueOf('Reposición', 'Últimos 7 días')).toHaveTextContent('9');
    expect(valueOf('Reposición', 'Últimos 14 días')).toHaveTextContent('20');
    expect(valueOf('Reposición', 'Últimos 21 días')).toHaveTextContent('31');
    expect(valueOf('Reposición', 'Últimos 30 días')).toHaveTextContent('42');
  });

  it('shows the GMV with its currency, the days out of stock and the shipping urgency', () => {
    renderTab();
    expect(valueOf('Reposición', 'GMV 30 días')).toHaveTextContent('4.137.021,50 ARS');
    expect(valueOf('Reposición', 'Días sin stock (21 días)')).toHaveTextContent('2');
    expect(valueOf('Reposición', 'Urgencia de envío')).toHaveTextContent('normal');
    expect(valueOf('Reposición', 'Stock total en Full')).toHaveTextContent('20');
    expect(valueOf('Reposición', 'Consultado').textContent).toMatch(/\d{2}\/\d{2}\/\d{4}/);
  });

  it('a complete report has no partial badge', () => {
    renderTab();
    expect(screen.queryByText('Datos parciales')).not.toBeInTheDocument();
  });

  it('a partial report is badged, names what is missing, and keeps the figures it has', () => {
    renderTab(withReplenishment({ status: 'partial', content_missing: 'sales_history', units_7d: null, units_14d: null, units_21d: null, days_out_of_stock_21d: null }));
    const badge = screen.getByText('Datos parciales');
    expect(badge).toHaveAttribute('title', expect.stringContaining('sales_history'));
    expect(valueOf('Reposición', 'Últimos 30 días')).toHaveTextContent('42');
    expect(valueOf('Reposición', 'Últimos 7 días')).toHaveTextContent('—');
    expect(valueOf('Reposición', 'Días sin stock (21 días)')).toHaveTextContent('—');
  });

  it.each([
    ['not_found', 'Mercado Libre no tiene datos de reposición'],
    ['error', 'No se pudo consultar la reposición'],
    ['never_fetched', 'Todavía no se consultó la reposición'],
  ])('%s says so and shows no invented figures', (status, message) => {
    renderTab(
      withReplenishment({ status, units_30d: null, gmv_30d: null, currency: null, units_7d: null, units_14d: null, units_21d: null, days_out_of_stock_21d: null, total_stock: null, shipping_urgency: null }),
    );
    expect(within(section('Reposición')).getByText(new RegExp(message))).toBeInTheDocument();
    expect(valueOf('Reposición', 'Últimos 30 días')).toHaveTextContent('—');
    expect(valueOf('Reposición', 'GMV 30 días')).toHaveTextContent('—');
    expect(within(section('Reposición')).queryByText('0')).not.toBeInTheDocument();
  });

  it('a real 0 days out of stock is shown as 0', () => {
    renderTab(withReplenishment({ days_out_of_stock_21d: 0 }));
    expect(valueOf('Reposición', 'Días sin stock (21 días)')).toHaveTextContent('0');
  });
});

describe('the replenishment flag is off', () => {
  const OFF = {
    ...DATA_STATE_OK,
    degraded: true,
    degradations: [{ code: 'resource_not_collected', resource: 'replenishment', affects: ['replenishment'] }],
  };

  it('says why there is nothing, instead of showing zeros', () => {
    renderTab(withReplenishment({ status: 'never_fetched', units_30d: null, gmv_30d: null, currency: null, fetched_at: null }), OFF);
    expect(within(section('Reposición')).getByText(/La reposición de Full no se sincroniza/)).toBeInTheDocument();
    expect(valueOf('Reposición', 'Últimos 30 días')).toHaveTextContent('—');
  });

  it('is also read from a disabled flag', () => {
    renderTab(DETAIL_RESPONSE, { ...DATA_STATE_OK, degradations: [{ code: 'flag_disabled', flag: 'replenishment', affects: ['replenishment'] }] });
    expect(within(section('Reposición')).getByText(/La reposición de Full no se sincroniza/)).toBeInTheDocument();
  });

  it('does not say it when the report is collected', () => {
    renderTab();
    expect(screen.queryByText(/no se sincroniza/)).not.toBeInTheDocument();
  });
});

describe('a publication that is not Full', () => {
  it('has no replenishment report to show', () => {
    renderTab(makeDetail({ row: ITEMS[1], replenishment: null }));
    expect(within(section('Reposición')).getByText('Esta publicación no es Full: no hay reposición.')).toBeInTheDocument();
  });
});
