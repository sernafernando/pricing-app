import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../../services/api';
import ModalVincularFactura from './ModalVincularFactura';

// NOTE: vite.config.js sets `css: false` for the test run, so CSS Module class
// names do NOT resolve. Never assert on className — assert on text and roles.
//
// The global PermisosContext mock in src/test/setup.js grants every permission,
// so `canAdjust` is true here: when the adjustment control is absent it is
// because of the currency guard, not because of a missing permission.

const PEDIDO_USD = { id: 1, numero: 'PC-0001', monto: '1000.00', moneda: 'USD' };
const PEDIDO_ARS = { id: 2, numero: 'PC-0002', monto: '1000.00', moneda: 'ARS' };

// ERP convention: curr_id_transaction 1=ARS, 2=USD.
const FACTURA_ARS = {
  ct_transaction: 900001,
  ct_docnumber: 'FC-A-0001',
  ct_date: '2026-02-10T00:00:00',
  ct_total: '1500000.00',
  curr_id_transaction: 1,
};
const FACTURA_USD = {
  ct_transaction: 900002,
  ct_docnumber: 'FC-B-0002',
  ct_date: '2026-02-11T00:00:00',
  ct_total: '1000.00',
  curr_id_transaction: 2,
};
const FACTURA_SIN_MONEDA = {
  ct_transaction: 900003,
  ct_docnumber: 'FC-C-0003',
  ct_date: '2026-02-12T00:00:00',
  ct_total: '1500000.00',
  curr_id_transaction: null,
};

async function renderModal(pedido, candidatas) {
  api.get.mockResolvedValue({ data: candidatas });
  const result = render(<ModalVincularFactura pedido={pedido} onClose={vi.fn()} />);
  await screen.findByText(candidatas[0].ct_docnumber);
  return result;
}

/** Selects the single listed invoice so the comparison block renders. */
async function seleccionarUnica() {
  const user = userEvent.setup();
  await user.click(screen.getByRole('radio'));
  return user;
}

describe('ModalVincularFactura — ERP invoice renders in its OWN currency', () => {
  /**
   * THE regression guard. The original bug formatted every ERP invoice with the
   * PEDIDO's currency, so a 1.500.000 ARS invoice sitting on a USD pedido was
   * displayed as "US$1.500.000,00" — off by the exchange rate, and confidently so.
   */
  it('shows an ARS invoice on a USD pedido with $, never US$', async () => {
    await renderModal(PEDIDO_USD, [FACTURA_ARS]);

    expect(screen.getByText('$1.500.000,00')).toBeInTheDocument();
    expect(screen.queryByText('US$1.500.000,00')).not.toBeInTheDocument();

    // Belt and braces: "$1.500.000,00" is a SUBSTRING of "US$1.500.000,00", so
    // assert no rendered node carries the USD prefix on this amount at all.
    expect(document.body.textContent).not.toContain('US$1.500.000,00');
  });

  it('shows a USD invoice on an ARS pedido with US$', async () => {
    await renderModal(PEDIDO_ARS, [FACTURA_USD]);

    expect(screen.getByText('US$1.000,00')).toBeInTheDocument();
  });

  it('shows no currency symbol when curr_id_transaction is null', async () => {
    await renderModal(PEDIDO_USD, [FACTURA_SIN_MONEDA]);

    expect(screen.getByText('1.500.000,00 (moneda desconocida)')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('US$1.500.000,00');
    expect(document.body.textContent).not.toContain('$1.500.000,00');
  });
});

describe('ModalVincularFactura — cross-currency comparison is refused', () => {
  it('states the currencies differ and shows no numeric difference', async () => {
    await renderModal(PEDIDO_USD, [FACTURA_ARS]);
    await seleccionarUnica();

    expect(screen.getByRole('status')).toHaveTextContent(
      'El pedido está en USD y la factura en ARS. Los montos no son comparables: no se puede calcular la diferencia ni ajustar el monto del pedido.',
    );

    // 1500000 - 1000 = 1499000 is an arithmetic result across two currencies:
    // meaningless, and it must never reach the screen.
    expect(screen.queryByText(/Diferencia/)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain('1.499.000,00');
  });

  it('does not offer the adjustment control on a currency mismatch', async () => {
    await renderModal(PEDIDO_USD, [FACTURA_ARS]);
    await seleccionarUnica();

    // The backend rejects a cross-currency adjustment outright
    // (`_validar_moneda_factura_coincide`), so offering it can only produce a
    // 400 — or, worse, a bogus accounting adjustment if that guard ever moves.
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Ajustar el monto del pedido al valor de la factura'),
    ).not.toBeInTheDocument();
  });

  it('never labels the confirm button as adjusting when currencies differ', async () => {
    await renderModal(PEDIDO_USD, [FACTURA_ARS]);
    await seleccionarUnica();

    expect(screen.getByRole('button', { name: 'Vincular' })).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Vincular y ajustar' }),
    ).not.toBeInTheDocument();
  });
});

describe('ModalVincularFactura — matching currencies behave exactly as before', () => {
  it('shows the signed difference and offers the adjustment', async () => {
    // Same currency on both sides → the subtraction is meaningful again.
    await renderModal(PEDIDO_ARS, [{ ...FACTURA_ARS, ct_total: '1500.00' }]);
    await seleccionarUnica();

    expect(screen.getByText('+$500,00')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(
      screen.getByText('Ajustar el monto del pedido al valor de la factura'),
    ).toBeInTheDocument();
  });

  it('reports amounts as matching when they are equal in the same currency', async () => {
    await renderModal(PEDIDO_ARS, [{ ...FACTURA_ARS, ct_total: '1000.00' }]);
    await seleccionarUnica();

    expect(screen.getByText(/Coinciden/)).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });
});
