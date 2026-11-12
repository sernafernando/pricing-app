import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import CostoCell from './CostoCell';

// The Publicaciones ML format; Productos passes its own (`USD $17.04`).
const format = (monto, moneda) => `${moneda} ${monto.toFixed(2).replace('.', ',')}`;

const PPP = { costo: 17.04, moneda: 'USD', fecha: '2026-08-27', markups: {} };
// A real shape: 17.04 USD at 1570 = 26752.80 ARS; the lot gives 963.10 ARS off (0.6134 USD at that same rate).
const SELL_IN_USD = {
  compra_item_id: 7,
  bono_id: null,
  bono_ids: [],
  descuento_unit: 963.1,
  costo: 25789.7,
  unidades_restantes: 12,
  moneda_costo: 'USD',
  costo_moneda: 16.4266,
  descuento_unit_moneda: 0.6134,
};
const SELL_IN_ARS = {
  ...SELL_IN_USD,
  descuento_unit: 100,
  costo: 39900,
  moneda_costo: 'ARS',
  costo_moneda: 39900,
  descuento_unit_moneda: 100,
};

const cell = (container) => container.firstChild;

describe('CostoCell — the unit cost in its own currency, one line (S10, S10b)', () => {
  it('shows a USD cost and its cost with sell in in USD on one line, the pesos and the PPP only in the tooltip', () => {
    const { container } = render(
      <CostoCell monto={17.04} moneda="USD" ppp={PPP} sellInOut={{ sell_in: SELL_IN_USD }} format={format} />,
    );
    expect(cell(container).textContent).toBe('USD 17,04 c/ sell in USD 16,43');
    expect(screen.queryByText(/ARS/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ppp/)).not.toBeInTheDocument();
    const title = cell(container).getAttribute('title');
    expect(title).toContain('ppp: USD $17.04 (27/08/26)');
    expect(title).toContain('c/ sell in en pesos: ARS 25789,70');
    expect(title).toContain('Descuento de sell in por unidad: USD 0,61 (ARS 963,10)');
    expect(title).toContain('Unidades restantes del lote: 12');
  });

  it('keeps an ARS cost in ARS, with no second pesos figure', () => {
    const { container } = render(
      <CostoCell monto={40000} moneda="ARS" ppp={null} sellInOut={{ sell_in: SELL_IN_ARS }} format={format} />,
    );
    expect(cell(container).textContent).toBe('ARS 40000,00 c/ sell in ARS 39900,00');
    const title = cell(container).getAttribute('title');
    expect(title).toContain('sin PPP');
    expect(title).not.toContain('en pesos');
    expect(title).toContain('Descuento de sell in por unidad: ARS 100,00 ·');
  });

  it('shows the cost with sell in as pending when it has no value in the cost currency, never a number', () => {
    const pendiente = { ...SELL_IN_USD, costo: null, costo_moneda: null, descuento_unit_moneda: null };
    const { container } = render(
      <CostoCell monto={17.04} moneda="USD" ppp={PPP} sellInOut={{ sell_in: pendiente }} format={format} />,
    );
    expect(cell(container).textContent).toBe('USD 17,04 c/ sell in pendiente');
  });

  it('is the cost alone without sell in, the PPP still in the tooltip', () => {
    const { container } = render(<CostoCell monto={17.04} moneda="USD" ppp={PPP} sellInOut={null} format={format} />);
    expect(cell(container).textContent).toBe('USD 17,04');
    expect(cell(container).getAttribute('title')).toBe('ppp: USD $17.04 (27/08/26)');
  });

  it('names the cost bonuses as the origin of a sell in without a lot', () => {
    const bono = { ...SELL_IN_ARS, compra_item_id: null, bono_id: 4, bono_ids: [4, 9], unidades_restantes: null };
    const { container } = render(
      <CostoCell monto={40000} moneda="ARS" ppp={null} sellInOut={{ sell_in: bono }} format={format} />,
    );
    expect(cell(container).getAttribute('title')).toContain('Bonos #4, #9 sobre el costo');
  });
});
