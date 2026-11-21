import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import SellInOutLine from './SellInOutLine';

const SELL_IN = { compra_item_id: 7, descuento_unit: 150, costo: 850.5, unidades_restantes: 12 };
const SELL_OUT = { monto_unit: 40, campana_ids: [3, 5] };

describe('SellInOutLine — sell out markup companion line (D1: markups over costo SI)', () => {
  it('renders nothing when sell_in_out is null (row unchanged)', () => {
    const { container } = render(<SellInOutLine sellInOut={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing in markup mode when sell_in_out is undefined', () => {
    const { container } = render(<SellInOutLine sellInOut={undefined} markupKey="clasica" />);
    expect(container.innerHTML).toBe('');
  });

  describe('markup mode', () => {
    it('shows only the markup c/ SO for the key, never a "c/ sell in" markup', () => {
      render(
        <SellInOutLine
          sellInOut={{
            sell_in: SELL_IN,
            sell_out: SELL_OUT,
            markups_sell_in: { clasica: 20.5, pvp_clasica: 99 },
            markups_sell_in_out: { clasica: 25.25, pvp_clasica: 98 },
          }}
          markupKey="clasica"
        />
      );
      expect(screen.getByText('c/ SO: 25.25%')).toBeTruthy();
      expect(screen.queryByText(/c\/ sell in/)).toBeNull();
      expect(screen.queryByText(/20\.50%/)).toBeNull();
      expect(screen.queryByText(/99\.00%/)).toBeNull();
    });

    it('labels the markup "c/ SO" when there is no sell in', () => {
      render(
        <SellInOutLine
          sellInOut={{
            sell_in: null,
            sell_out: SELL_OUT,
            markups_sell_in: {},
            markups_sell_in_out: { pvp_cuota_6: 12 },
          }}
          markupKey="pvp_cuota_6"
        />
      );
      expect(screen.getByText('c/ SO: 12.00%')).toBeTruthy();
      expect(screen.queryByText(/c\/ sell/)).toBeNull();
    });

    it('scales the raw-ratio mejor_oferta key by x100', () => {
      render(
        <SellInOutLine
          sellInOut={{
            sell_in: SELL_IN,
            sell_out: SELL_OUT,
            markups_sell_in: { mejor_oferta: 0.3 },
            markups_sell_in_out: { mejor_oferta: 0.355 },
          }}
          markupKey="mejor_oferta"
        />
      );
      expect(screen.getByText('c/ SO: 35.50%')).toBeTruthy();
      expect(screen.queryByText(/30\.00%/)).toBeNull();
    });

    it('shows sell out as pending when its amount is unknown, never a fake number', () => {
      render(
        <SellInOutLine
          sellInOut={{
            sell_in: SELL_IN,
            sell_out: { monto_unit: null, campana_ids: [3] },
            markups_sell_in: { clasica: 20.5 },
            markups_sell_in_out: {},
          }}
          markupKey="clasica"
        />
      );
      const pendiente = screen.getByText('c/ SO: pendiente');
      expect(pendiente.getAttribute('title')).toBe(
        'Monto de sell out pendiente: falta el tipo de cambio o la base de la campaña'
      );
      expect(screen.queryByText(/c\/ sell in/)).toBeNull();
    });

    it('names the sell out amount per unit and its campaigns in the tooltip', () => {
      render(
        <SellInOutLine
          sellInOut={{
            sell_in: null,
            sell_out: SELL_OUT,
            markups_sell_in: {},
            markups_sell_in_out: { clasica: 12 },
          }}
          markupKey="clasica"
        />
      );
      expect(screen.getByText('c/ SO: 12.00%').getAttribute('title')).toBe(
        'Sell out por unidad: ARS $40.00 · Campañas: #3, #5'
      );
    });

    it('renders nothing for a sell in without sell out, even with a recorded markup', () => {
      const { container } = render(
        <SellInOutLine
          sellInOut={{ sell_in: SELL_IN, sell_out: null, markups_sell_in: { clasica: 20.5 }, markups_sell_in_out: {} }}
          markupKey="clasica"
        />
      );
      expect(container.innerHTML).toBe('');
    });

    it('renders nothing for a sell in without ARS cost and no sell out (no pending markup c/ sell in)', () => {
      const { container } = render(
        <SellInOutLine
          sellInOut={{
            sell_in: { ...SELL_IN, costo: null },
            sell_out: null,
            markups_sell_in: {},
            markups_sell_in_out: {},
          }}
          markupKey="clasica"
        />
      );
      expect(container.innerHTML).toBe('');
    });

    it('does not mark the sell out markup pending only because the sell in lot has no ARS cost', () => {
      render(
        <SellInOutLine
          sellInOut={{
            sell_in: { ...SELL_IN, costo: null },
            sell_out: SELL_OUT,
            markups_sell_in: {},
            markups_sell_in_out: { clasica: 14 },
          }}
          markupKey="clasica"
        />
      );
      expect(screen.getByText('c/ SO: 14.00%')).toBeTruthy();
      expect(screen.queryByText(/pendiente/)).toBeNull();
    });

    it('omits a figure whose key was not recorded, without falling back to a sibling key', () => {
      const { container } = render(
        <SellInOutLine
          sellInOut={{
            sell_in: SELL_IN,
            sell_out: SELL_OUT,
            markups_sell_in: { cuota_clasica_3: 10 },
            markups_sell_in_out: { cuota_clasica_3: 11 },
          }}
          markupKey="cuota_clasica_30"
        />
      );
      expect(container.innerHTML).toBe('');
    });
  });
});
