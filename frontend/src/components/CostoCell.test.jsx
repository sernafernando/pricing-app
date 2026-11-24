import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import CostoCell from './CostoCell';

// The Publicaciones ML format; Productos passes its own (`USD $17.04`).
const format = (monto, moneda) => `${moneda} ${monto.toFixed(2).replace('.', ',')}`;

const PPP = { costo: 17.04, moneda: 'USD', fecha: '2026-08-27', markups: {} };
// The retired sell in figure an older payload may still carry (costo SI T5 PR B): never rendered.
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
  it('shows a USD cost on one line, the PPP only in the tooltip', () => {
    const { container } = render(<CostoCell monto={17.04} moneda="USD" ppp={PPP} format={format} />);
    expect(cell(container).textContent).toBe('USD 17,04');
    expect(screen.queryByText(/ppp/)).not.toBeInTheDocument();
    expect(cell(container).getAttribute('title')).toBe('ppp: USD $17.04 (27/08/26)');
  });

  it('reads "sin PPP" when the PPP is null', () => {
    const { container } = render(<CostoCell monto={40000} moneda="ARS" ppp={null} format={format} />);
    expect(cell(container).textContent).toBe('ARS 40000,00');
    expect(cell(container).getAttribute('title')).toBe('sin PPP');
  });

  // costo SI T5 PR B: costo SI replaced the FIFO lots and the per-sale cost bonuses, so there is no "c/ sell in".
  it.each([
    ['a lot', { sell_in: SELL_IN_USD }],
    ['a cost bonus', { sell_in: { ...SELL_IN_ARS, compra_item_id: null, bono_id: 4, bono_ids: [4, 9] } }],
  ])('shows no cost with sell in even when an older payload still carries %s', (_, sellInOut) => {
    const { container } = render(
      <CostoCell monto={17.04} moneda="USD" ppp={PPP} sellInOut={sellInOut} format={format} />,
    );
    expect(cell(container).textContent).toBe('USD 17,04');
    expect(container.textContent).not.toMatch(/sell in/);
    expect(cell(container).getAttribute('title')).toBe('ppp: USD $17.04 (27/08/26)');
  });

  it('has no tooltip without a PPP to show', () => {
    const { container } = render(<CostoCell monto={17.04} moneda="USD" format={format} />);
    expect(cell(container).getAttribute('title')).toBeNull();
  });
});
