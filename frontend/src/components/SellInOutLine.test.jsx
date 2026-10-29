import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import SellInOutLine from './SellInOutLine';

const SELL_IN = { compra_item_id: 7, descuento_unit: 150, costo: 850.5, unidades_restantes: 12 };
const SELL_OUT = { monto_unit: 40, campana_ids: [3, 5] };

describe('SellInOutLine — sell in / sell out companion line', () => {
  it('renders nothing when sell_in_out is null (row unchanged)', () => {
    const { container } = render(<SellInOutLine sellInOut={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing in markup mode when sell_in_out is undefined', () => {
    const { container } = render(<SellInOutLine sellInOut={undefined} markupKey="clasica" />);
    expect(container.innerHTML).toBe('');
  });

  describe('cost mode (no markupKey)', () => {
    it('shows the cost with sell in, in ARS', () => {
      render(<SellInOutLine sellInOut={{ sell_in: SELL_IN, sell_out: null }} />);
      expect(screen.getByText('c/ sell in: ARS $850.50')).toBeTruthy();
    });

    it('names the discount per unit and the remaining units of the lot in the tooltip', () => {
      render(<SellInOutLine sellInOut={{ sell_in: SELL_IN, sell_out: null }} />);
      const line = screen.getByText('c/ sell in: ARS $850.50');
      expect(line.getAttribute('title')).toBe(
        'Descuento de sell in por unidad: ARS $150.00 · Unidades restantes del lote: 12'
      );
    });

    it('names the % of cost bonus instead of a lot when the sell in has no units left (T25c)', () => {
      const bono = { ...SELL_IN, compra_item_id: null, bono_id: 4, unidades_restantes: null };
      render(<SellInOutLine sellInOut={{ sell_in: bono, sell_out: null }} />);
      const line = screen.getByText('c/ sell in: ARS $850.50');
      expect(line.getAttribute('title')).toBe('Descuento de sell in por unidad: ARS $150.00 · Bono #4 sobre el costo');
    });

    it('names every stacked % of cost bonus (T25c)', () => {
      const bonos = { ...SELL_IN, compra_item_id: null, bono_id: 4, bono_ids: [4, 7], unidades_restantes: null };
      render(<SellInOutLine sellInOut={{ sell_in: bonos, sell_out: null }} />);
      const line = screen.getByText('c/ sell in: ARS $850.50');
      expect(line.getAttribute('title')).toBe(
        'Descuento de sell in por unidad: ARS $150.00 · Bonos #4, #7 sobre el costo',
      );
    });

    it('shows the cost with sell in as pending when it has no ARS value, never a number', () => {
      render(<SellInOutLine sellInOut={{ sell_in: { ...SELL_IN, costo: null }, sell_out: null }} />);
      expect(screen.getByText('c/ sell in: pendiente')).toBeTruthy();
    });

    it('renders nothing when only sell out applies (cost with sell in = cost)', () => {
      const { container } = render(<SellInOutLine sellInOut={{ sell_in: null, sell_out: SELL_OUT }} />);
      expect(container.innerHTML).toBe('');
    });
  });

  describe('markup mode', () => {
    it('shows the markup with sell in and with sell in + sell out for the key', () => {
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
      expect(screen.getByText('c/ sell in: 20.50%')).toBeTruthy();
      expect(screen.getByText('c/ sell in + sell out: 25.25%')).toBeTruthy();
      expect(screen.queryByText(/99\.00%/)).toBeNull();
    });

    it('labels the combined markup "c/ sell out" when there is no sell in', () => {
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
      expect(screen.getByText('c/ sell out: 12.00%')).toBeTruthy();
      expect(screen.queryByText(/c\/ sell in/)).toBeNull();
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
      expect(screen.getByText('c/ sell in: 30.00%')).toBeTruthy();
      expect(screen.getByText('c/ sell in + sell out: 35.50%')).toBeTruthy();
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
      expect(screen.getByText('c/ sell in: 20.50%')).toBeTruthy();
      const pendiente = screen.getByText('c/ sell in + sell out: pendiente');
      expect(pendiente.getAttribute('title')).toBe(
        'Monto de sell out pendiente: falta el tipo de cambio o la base de la campaña'
      );
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
      expect(screen.getByText('c/ sell out: 12.00%').getAttribute('title')).toBe(
        'Sell out por unidad: ARS $40.00 · Campañas: #3, #5'
      );
    });

    it('shows the markup with sell in as pending when the cost with sell in has no ARS value', () => {
      render(
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
      expect(screen.getByText('c/ sell in: pendiente')).toBeTruthy();
    });

    it('shows sell in + sell out as pending when the cost with sell in has no ARS value', () => {
      render(
        <SellInOutLine
          sellInOut={{
            sell_in: { ...SELL_IN, costo: null },
            sell_out: SELL_OUT,
            markups_sell_in: {},
            markups_sell_in_out: {},
          }}
          markupKey="clasica"
        />
      );
      expect(screen.getByText('c/ sell in: pendiente')).toBeTruthy();
      expect(screen.getByText('c/ sell in + sell out: pendiente')).toBeTruthy();
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
