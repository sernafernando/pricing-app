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
// A USD pedido carries its OWN tipo_cambio; ERP documents never do. 1000 @ 1500
// → 1.500.000 ARS, which is what makes the cross-currency comparison possible.
const PEDIDO_USD_CON_TC = {
  id: 3,
  numero: 'PC-0003',
  monto: '1000.00',
  moneda: 'USD',
  tipo_cambio: '1500.00',
};

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

describe('ModalVincularFactura — pedido USD with TC vs. factura ARS', () => {
  // 100% of the ERP purchase documents are ARS (4578 transactions / 19 months),
  // and pedidos can be USD — so pedido USD + factura ARS is the ONLY
  // cross-currency case that actually occurs. The company's functional currency
  // is ARS and the pedido carries its own TC, so the two ARE comparable there.

  it('computes and shows the difference in ARS', async () => {
    // 1000 USD @ 1500 = 1.500.000 ARS vs. a 1.600.000 ARS invoice → +100.000 ARS.
    await renderModal(PEDIDO_USD_CON_TC, [
      { ...FACTURA_ARS, ct_total: '1600000.00' },
    ]);
    await seleccionarUnica();

    expect(screen.getByText('+$100.000,00')).toBeInTheDocument();
    // The difference is an ARS figure: labelling it US$ would be off by the TC.
    expect(document.body.textContent).not.toContain('+US$100.000,00');
    // The "not comparable" banner from #1063 must be gone for this case.
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  /**
   * THE test of this change. Making the amounts comparable for DISPLAY must not
   * re-enable the WRITE path: `ajustar_monto` rewrites `pedido.monto` in the
   * pedido's own currency, and the backend refuses a cross-currency adjustment
   * (`_validar_moneda_factura_coincide`). Pedido P-02-2026-00001 ended up with a
   * 46M USD monto exactly because those two concepts were fused.
   */
  it('does NOT offer the adjustment even though the difference is shown', async () => {
    await renderModal(PEDIDO_USD_CON_TC, [
      { ...FACTURA_ARS, ct_total: '1600000.00' },
    ]);
    await seleccionarUnica();

    // Difference IS on screen…
    expect(screen.getByText('+$100.000,00')).toBeInTheDocument();
    // …and the adjustment is still refused.
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Ajustar el monto del pedido al valor de la factura'),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Vincular' })).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Vincular y ajustar' }),
    ).not.toBeInTheDocument();
  });

  /**
   * `ajustar` is checkbox state that survives changing the selected invoice, so
   * the payload must be derived (`ajustarEfectivo`), never read off the raw
   * state. The cross-currency case is the dangerous one now: the difference IS
   * on screen, so nothing on the page suggests the tick is no longer honoured.
   */
  it('never POSTs ajustar_monto after switching to the cross-currency invoice', async () => {
    api.post.mockClear();
    await renderModal(PEDIDO_USD_CON_TC, [
      { ...FACTURA_USD, ct_total: '1200.00' }, // same currency → adjustable
      { ...FACTURA_ARS, ct_total: '1600000.00' }, // cross-currency → not
    ]);
    const user = userEvent.setup();

    // Select the USD invoice, tick the adjustment, fill the motivo.
    await user.click(screen.getAllByRole('radio')[0]);
    await user.click(screen.getByRole('checkbox'));
    await user.type(screen.getByRole('textbox'), 'Ajuste de prueba');

    // Now switch to the ARS invoice: the checkbox disappears, but `ajustar`
    // is still true underneath.
    await user.click(screen.getAllByRole('radio')[1]);
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Vincular' }));

    expect(api.post).toHaveBeenCalledTimes(1);
    const [, body] = api.post.mock.calls[0];
    expect(body.ajustar_monto).toBe(false);
    expect(body.nuevo_monto).toBeUndefined();
    expect(body.motivo_ajuste).toBeUndefined();
  });

  it('states the TC used and why the adjustment is unavailable', async () => {
    // A converted number that does not say at what rate is not an improvement.
    await renderModal(PEDIDO_USD_CON_TC, [
      { ...FACTURA_ARS, ct_total: '1600000.00' },
    ]);
    await seleccionarUnica();

    expect(document.body.textContent).toContain(
      'La diferencia se calcula en ARS convirtiendo el pedido al TC 1.500,00',
    );
    expect(document.body.textContent).toContain(
      'no se puede ajustar el monto del pedido contra esta factura',
    );
  });

  it('reports the amounts as matching when they are equal once in ARS', async () => {
    // 1000 USD @ 1500 = exactly the 1.500.000 ARS invoice.
    await renderModal(PEDIDO_USD_CON_TC, [FACTURA_ARS]);
    await seleccionarUnica();

    expect(screen.getByText(/Coinciden/)).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('renders the pedido ARS-first with the USD native amount and its TC', async () => {
    // Invoice at 1.600.000 so the pedido's 1.500.000 ARS equivalent is the only
    // node carrying that figure — otherwise this would pass on the table cell.
    await renderModal(PEDIDO_USD_CON_TC, [
      { ...FACTURA_ARS, ct_total: '1600000.00' },
    ]);
    await seleccionarUnica();

    // Primary figure: the ARS equivalent (1000 USD @ 1500).
    expect(screen.getByText('$1.500.000,00')).toBeInTheDocument();
    // Secondary, muted: the native USD amount AND the rate it was converted at.
    expect(document.body.textContent).toContain('US$1.000,00 @ TC 1.500,00');
  });
});

describe('ModalVincularFactura — a USD pedido without TC stays incomparable', () => {
  it('shows no difference and no adjustment against an ARS invoice', async () => {
    // No TC → no ARS equivalent. We do NOT invent a rate and do NOT use today's.
    await renderModal(PEDIDO_USD, [{ ...FACTURA_ARS, ct_total: '1600000.00' }]);
    await seleccionarUnica();

    expect(screen.getByRole('status')).toHaveTextContent(
      'Los montos no son comparables',
    );
    expect(screen.queryByText(/Diferencia/)).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();

    // The pedido keeps rendering in its native currency, with no invented rate.
    expect(screen.getByText('US$1.000,00')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('@ TC');
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

  it('keeps a USD pedido vs. USD invoice native and adjustable', async () => {
    // Regression guard for this change: an ERP document has no TC, so routing
    // USD↔USD through the ARS conversion would have made it "not comparable"
    // and silently removed an adjustment that #1063 correctly allowed.
    await renderModal(PEDIDO_USD_CON_TC, [{ ...FACTURA_USD, ct_total: '1200.00' }]);
    await seleccionarUnica();

    // Same native currency → the difference stays in USD, which is the currency
    // the adjustment would actually write into `pedido.monto`.
    expect(screen.getByText('+US$200,00')).toBeInTheDocument();
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
