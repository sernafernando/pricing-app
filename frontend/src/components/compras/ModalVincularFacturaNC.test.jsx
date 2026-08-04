import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ModalVincularFacturaNC from './ModalVincularFacturaNC';

// NOTE: vite.config.js sets `css: false` for the test run, so CSS Module class
// names do NOT resolve. Never assert on className — assert on text and roles.
//
// The global PermisosContext mock in src/test/setup.js grants every permission,
// so `canAdjust` is true here: when the adjustment control is absent it is
// because of the currency guard, not because of a missing permission.

// The hook's return value MUST be referentially stable: `fetchCandidatas` is a
// useCallback keyed on `listarCandidatasERP`, so handing back a fresh object on
// every render re-fires the mount effect forever and the modal never leaves its
// loading state.
const { listarCandidatasERP, vincularFactura, hookValue } = vi.hoisted(() => {
  const listar = vi.fn();
  const vincular = vi.fn();
  return {
    listarCandidatasERP: listar,
    vincularFactura: vincular,
    hookValue: { listarCandidatasERP: listar, vincularFactura: vincular },
  };
});

vi.mock('../../hooks/useNCsLocales', () => ({ default: () => hookValue }));

const NC_LOCAL_ARS = { id: 5, numero: 'NC-0001', monto: '1000.00', moneda: 'ARS' };

// ERP convention: curr_id_transaction 1=ARS, 2=USD.
const NC_ERP_ARS = {
  ct_transaction: 800001,
  ct_docnumber: 'NCE-A-0001',
  ct_date: '2026-03-01T00:00:00',
  ct_total: '1500.00',
  curr_id_transaction: 1,
};
const NC_ERP_USD = {
  ct_transaction: 800002,
  ct_docnumber: 'NCE-B-0002',
  ct_date: '2026-03-02T00:00:00',
  ct_total: '1500000.00',
  curr_id_transaction: 2,
};
const NC_ERP_SIN_MONEDA = {
  ct_transaction: 800003,
  ct_docnumber: 'NCE-C-0003',
  ct_date: '2026-03-03T00:00:00',
  ct_total: '1500000.00',
  curr_id_transaction: null,
};

beforeEach(() => {
  listarCandidatasERP.mockReset();
  vincularFactura.mockReset().mockResolvedValue({});
});

async function renderModal(candidatas, nc = NC_LOCAL_ARS) {
  listarCandidatasERP.mockResolvedValue(candidatas);
  const result = render(<ModalVincularFacturaNC nc={nc} onClose={vi.fn()} />);
  await screen.findByText(candidatas[0].ct_docnumber);
  return result;
}

/** Selects a listed ERP NC by its position in the rendered table. */
async function seleccionar(user, indice) {
  await user.click(screen.getAllByRole('radio')[indice]);
}

describe('ModalVincularFacturaNC — ERP NC renders in its OWN currency', () => {
  it('shows a USD ERP NC with US$ even though the local NC is ARS', async () => {
    await renderModal([NC_ERP_USD]);

    expect(screen.getByText('US$1.500.000,00')).toBeInTheDocument();
    // Exact-text query: it does NOT match the "US$…" node, so this fails the
    // moment the amount is rendered with the local NC's ARS symbol again.
    expect(screen.queryByText('$1.500.000,00')).not.toBeInTheDocument();
  });

  it('shows an ARS ERP NC with $', async () => {
    await renderModal([NC_ERP_ARS]);

    expect(screen.getByText('$1.500,00')).toBeInTheDocument();
  });

  it('shows no currency symbol when curr_id_transaction is null', async () => {
    await renderModal([NC_ERP_SIN_MONEDA]);

    expect(screen.getByText('1.500.000,00 (moneda desconocida)')).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('$1.500.000,00');
  });
});

describe('ModalVincularFacturaNC — cross-currency difference is refused', () => {
  it('states the currencies differ and shows no numeric difference', async () => {
    const user = userEvent.setup();
    await renderModal([NC_ERP_USD]);
    await seleccionar(user, 0);

    expect(screen.getByRole('status')).toHaveTextContent(
      'La NC local está en ARS y la NC del ERP en USD. Los montos no son comparables: no se puede calcular la diferencia ni ajustar el monto de la NC local.',
    );

    // 1500000 - 1000 across two currencies is not a difference, it is noise.
    expect(screen.queryByText(/Diferencia/)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain('1.499.000,00');
  });

  it('treats an unknown ERP currency as not comparable either', async () => {
    const user = userEvent.setup();
    await renderModal([NC_ERP_SIN_MONEDA]);
    await seleccionar(user, 0);

    expect(screen.getByRole('status')).toHaveTextContent('moneda desconocida');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('does not offer the adjustment control on a currency mismatch', async () => {
    const user = userEvent.setup();
    await renderModal([NC_ERP_USD]);
    await seleccionar(user, 0);

    // hayDiferencia gates the adjustment flow; a currency mismatch must not be
    // able to drive a bogus accounting adjustment.
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Ajustar el monto de la NC local al valor del ERP'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Vincular y ajustar' }),
    ).not.toBeInTheDocument();
  });

  it('never submits ajustar_monto after switching to a mismatched NC', async () => {
    const user = userEvent.setup();
    await renderModal([NC_ERP_ARS, NC_ERP_USD]);

    // Tick the adjustment on the comparable (ARS) NC and give it a motivo…
    await seleccionar(user, 0);
    await user.click(screen.getByRole('checkbox'));
    await user.type(screen.getByRole('textbox'), 'Diferencia por redondeo');

    // …then switch to the USD one. `ajustar` is user state that survives the
    // selection change, so it must not be trusted on its own.
    await seleccionar(user, 1);
    await user.click(screen.getByRole('button', { name: 'Vincular' }));

    expect(vincularFactura).toHaveBeenCalledTimes(1);
    const [, body] = vincularFactura.mock.calls[0];
    expect(body.ajustar_monto).toBe(false);
    expect(body).not.toHaveProperty('nuevo_monto');
    expect(body).not.toHaveProperty('motivo_ajuste');
  });
});

describe('ModalVincularFacturaNC — matching currencies behave exactly as before', () => {
  it('shows the signed difference and offers the adjustment', async () => {
    const user = userEvent.setup();
    await renderModal([NC_ERP_ARS]);
    await seleccionar(user, 0);

    expect(screen.getByText('+$500,00')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(
      screen.getByText('Ajustar el monto de la NC local al valor del ERP'),
    ).toBeInTheDocument();
  });

  it('still submits the adjustment when the currencies match', async () => {
    const user = userEvent.setup();
    await renderModal([NC_ERP_ARS]);
    await seleccionar(user, 0);

    await user.click(screen.getByRole('checkbox'));
    await user.type(screen.getByRole('textbox'), 'Diferencia por redondeo');
    await user.click(screen.getByRole('button', { name: 'Vincular y ajustar' }));

    expect(vincularFactura).toHaveBeenCalledTimes(1);
    const [, body] = vincularFactura.mock.calls[0];
    expect(body.ajustar_monto).toBe(true);
    expect(body.nuevo_monto).toBe('1500.00');
    expect(body.motivo_ajuste).toBe('Diferencia por redondeo');
  });

  it('reports amounts as matching when they are equal in the same currency', async () => {
    const user = userEvent.setup();
    await renderModal([{ ...NC_ERP_ARS, ct_total: '1000.00' }]);
    await seleccionar(user, 0);

    expect(screen.getByText(/Coinciden/)).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });
});
