import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../../services/api';
import ModalAplicarNC from './ModalAplicarNC';

// NOTE: vite.config.js sets `css: false` for the test run, so CSS Module class
// names do NOT resolve. Never assert on className — assert on text and roles.

// Referentially stable on purpose — see ModalVincularFacturaNC.test.jsx.
const { hookValue } = vi.hoisted(() => ({
  hookValue: { aplicar: vi.fn().mockResolvedValue({}) },
}));

vi.mock('../../hooks/useNCsLocales', () => ({ default: () => hookValue }));

const NC_LOCAL_ARS = {
  id: 5,
  numero: 'NC-0001',
  monto: '1000.00',
  saldo_pendiente: '1000.00',
  moneda: 'ARS',
  proveedor_id: 10,
};

// ERP convention: curr_id_transaction 1=ARS, 2=USD.
const FACTURA_USD = {
  ct_transaction: 700001,
  ct_docnumber: 'FC-USD-0001',
  ct_date: '2026-04-01T00:00:00',
  ct_total: '1000.00',
  curr_id_transaction: 2,
};
const FACTURA_ARS = {
  ct_transaction: 700002,
  ct_docnumber: 'FC-ARS-0002',
  ct_date: '2026-04-02T00:00:00',
  ct_total: '1500000.00',
  curr_id_transaction: 1,
};
const FACTURA_SIN_MONEDA = {
  ct_transaction: 700003,
  ct_docnumber: 'FC-NUL-0003',
  ct_date: '2026-04-03T00:00:00',
  ct_total: '1500000.00',
  curr_id_transaction: null,
};

/**
 * The modal fires two independent GETs on mount; route the shared api.get stub
 * by URL so the ERP invoice list is the only thing under test here.
 */
function mockEndpoints(facturas) {
  api.get.mockImplementation((url) => {
    if (url.includes('facturas-erp-vigentes')) return Promise.resolve({ data: facturas });
    return Promise.resolve({ data: [] });
  });
}

beforeEach(() => {
  api.get.mockReset();
});

/** Renders the modal and switches the destino to "Factura del ERP". */
async function renderConFacturas(facturas, nc = NC_LOCAL_ARS) {
  mockEndpoints(facturas);
  const user = userEvent.setup();
  render(<ModalAplicarNC nc={nc} onClose={vi.fn()} />);

  await user.click(screen.getByRole('radio', { name: 'Factura del ERP del proveedor' }));
  // findAllByRole: a mixed-currency case renders more than one FC- option.
  await screen.findAllByRole('option', { name: /FC-/ });
  return user;
}

describe('ModalAplicarNC — ERP invoice options render in their OWN currency', () => {
  /**
   * The endpoint is called with `?moneda=<nc.moneda>` so the list is normally
   * pre-filtered server-side — but the modal must not DEPEND on that filter to
   * be honest. When `nc.moneda` is absent the param is dropped and every
   * currency comes back, and the option list was formatting all of them with
   * the local NC's currency regardless.
   */
  it('shows a USD invoice with US$ even though the local NC is ARS', async () => {
    await renderConFacturas([FACTURA_USD]);

    expect(
      screen.getByRole('option', { name: /FC-USD-0001 .* US\$1\.000,00/ }),
    ).toBeInTheDocument();
  });

  it('shows an ARS invoice with $ and never US$', async () => {
    await renderConFacturas([FACTURA_ARS]);

    const opcion = screen.getByRole('option', { name: /FC-ARS-0002/ });
    expect(opcion.textContent).toContain('$1.500.000,00');
    expect(opcion.textContent).not.toContain('US$');
  });

  it('shows no currency symbol when curr_id_transaction is null', async () => {
    await renderConFacturas([FACTURA_SIN_MONEDA]);

    const opcion = screen.getByRole('option', { name: /FC-NUL-0003/ });
    expect(opcion.textContent).toContain('1.500.000,00 (moneda desconocida)');
    expect(opcion.textContent).not.toContain('$');
  });

  it('formats each invoice independently when currencies are mixed', async () => {
    // This is the state the `?moneda=` filter is supposed to prevent, but the
    // filter is server-side and optional — the UI must still be truthful.
    await renderConFacturas([FACTURA_USD, FACTURA_ARS]);

    expect(screen.getByRole('option', { name: /FC-USD-0001/ }).textContent).toContain(
      'US$1.000,00',
    );
    expect(screen.getByRole('option', { name: /FC-ARS-0002/ }).textContent).not.toContain(
      'US$',
    );
  });

  it('keeps formatting the local NC saldo with the local NC currency', async () => {
    // Guard against an over-correction: only ERP amounts change currency source.
    await renderConFacturas([FACTURA_USD]);

    expect(screen.getByText(/Máximo: \$1\.000,00 \(saldo de la NC\)/)).toBeInTheDocument();
  });
});
