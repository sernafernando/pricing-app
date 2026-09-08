/**
 * Tests for DesgloseDrawer.jsx (ml-ventas-desglose-costos, corte 6).
 *
 * Scope:
 *  - Renders nothing when closed.
 *  - Fetches GET /ml-ventas-ops/orders/{orderId} when open, and re-fetches
 *    when orderId changes while staying open (R2 — never closes on its own).
 *  - Renders lines exactly as sent, in order, with no filtering or renaming.
 *  - `incompleto` shows the plain-language reason and never hides the total.
 *  - Escape closes the panel; clicking the actual backdrop (not the panel
 *    itself) closes it too, and clicking inside the panel does not.
 *  - A stale response never overwrites what a newer row selection loaded
 *    (sequence guard, same pattern as `VentasML.jsx`'s `latestRequestRef`).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DesgloseDrawer from './DesgloseDrawer';
import api from '../services/api';

function mockBreakdown(orderId, breakdown) {
  api.get.mockImplementation((url) => {
    if (url === `/ml-ventas-ops/orders/${orderId}`) {
      return Promise.resolve({ data: { breakdown } });
    }
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  api.get.mockReset();
});

describe('Visibility', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<DesgloseDrawer orderId={1001} open={false} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('fetches the breakdown and renders it when open', async () => {
    mockBreakdown(1001, {
      lines: [
        { concepto: 'Cargo por vender', monto: 91250, origen: 'api' },
        { concepto: 'Costo por ofrecer cuotas', monto: 97820, origen: 'api' },
        { concepto: 'Envíos', monto: 15190, origen: 'api' },
      ],
      neto: 525740,
      incompleto: false,
      incomplete_reasons: [],
    });
    render(<DesgloseDrawer orderId={1001} open onClose={vi.fn()} />);

    expect(await screen.findByRole('dialog', { name: /desglose de costos/i })).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/orders/1001');

    // Rendered exactly as the backend sent them, in the given order.
    const items = await screen.findAllByRole('listitem');
    expect(items.map((li) => li.textContent)).toEqual([
      'Cargo por vender91.250,00',
      'Costo por ofrecer cuotas97.820,00',
      'Envíos15.190,00',
    ]);
    expect(screen.getByText('525.740,00')).toBeInTheDocument();
  });
});

describe('Switching orders without closing', () => {
  it('re-fetches when orderId changes while the drawer stays open', async () => {
    mockBreakdown(1001, {
      lines: [{ concepto: 'Cargo por vender', monto: 10, origen: 'api' }],
      neto: 90,
      incompleto: false,
      incomplete_reasons: [],
    });
    const { rerender } = render(<DesgloseDrawer orderId={1001} open onClose={vi.fn()} />);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/orders/1001'));

    mockBreakdown(1002, {
      lines: [{ concepto: 'Costo fijo', monto: 20, origen: 'api' }],
      neto: 80,
      incompleto: false,
      incomplete_reasons: [],
    });
    rerender(<DesgloseDrawer orderId={1002} open onClose={vi.fn()} />);

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/orders/1002'));
    expect(await screen.findByText('Costo fijo')).toBeInTheDocument();
    // Never unmounted between orders — the dialog stayed on screen the
    // whole time.
    expect(screen.getByRole('dialog', { name: /desglose de costos/i })).toBeInTheDocument();
  });
});

describe('Incomplete breakdown', () => {
  it('shows the plain-language reason for payments_not_synced, never the raw code', async () => {
    mockBreakdown(1001, {
      lines: [],
      neto: null,
      incompleto: true,
      incomplete_reasons: ['payments_not_synced'],
    });
    render(<DesgloseDrawer orderId={1001} open onClose={vi.fn()} />);

    expect(
      await screen.findByText(/todav[ií]a no los trajo/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('payments_not_synced')).not.toBeInTheDocument();
  });

  it('shows the plain-language reason for billing_not_swept and still shows the partial total, not a dash', async () => {
    mockBreakdown(1001, {
      lines: [{ concepto: 'Cargo por vender', monto: 100, origen: 'api' }],
      neto: 900,
      incompleto: true,
      incomplete_reasons: ['billing_not_swept'],
    });
    render(<DesgloseDrawer orderId={1001} open onClose={vi.fn()} />);

    expect(await screen.findByText(/falta el barrido de facturaci[oó]n/i)).toBeInTheDocument();
    // The real partial number stays visible — never hidden behind a dash.
    expect(screen.getByText('900,00')).toBeInTheDocument();
  });
});

describe('Closing', () => {
  it('calls onClose on Escape', async () => {
    mockBreakdown(1001, { lines: [], neto: null, incompleto: false, incomplete_reasons: [] });
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<DesgloseDrawer orderId={1001} open onClose={onClose} />);
    await screen.findByRole('dialog');

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onClose when the actual backdrop is clicked, but not when the panel itself is', async () => {
    mockBreakdown(1001, { lines: [], neto: null, incompleto: false, incomplete_reasons: [] });
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<DesgloseDrawer orderId={1001} open onClose={onClose} />);
    const dialog = await screen.findByRole('dialog');

    // Clicking inside the panel must NOT close it — this is the assertion
    // a fake "backdrop" test (clicking the dialog itself) cannot make,
    // since the dialog is inside the backdrop and the click would bubble
    // to the same handler either way.
    await user.click(dialog);
    expect(onClose).not.toHaveBeenCalled();

    // The backdrop element itself, distinct from the panel it wraps.
    await user.click(screen.getByTestId('drawer-overlay'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('Stale response guard', () => {
  it('never lets an older row selection overwrite a newer one, mirroring VentasML.jsx', async () => {
    const resolvers = {};
    api.get.mockImplementation((url) => {
      const match = url.match(/\/ml-ventas-ops\/orders\/(\d+)/);
      if (match) {
        return new Promise((resolve) => {
          resolvers[match[1]] = resolve;
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { rerender } = render(<DesgloseDrawer orderId={1001} open onClose={vi.fn()} />);
    await waitFor(() => expect(resolvers['1001']).toBeDefined());

    // Operator picks row B before A's response arrives.
    rerender(<DesgloseDrawer orderId={1002} open onClose={vi.fn()} />);
    await waitFor(() => expect(resolvers['1002']).toBeDefined());

    // B's response arrives FIRST, then the stale A response arrives LAST.
    resolvers['1002']({
      data: {
        breakdown: {
          lines: [{ concepto: 'Costo fijo', monto: 20, origen: 'api' }],
          neto: 80,
          incompleto: false,
          incomplete_reasons: [],
        },
      },
    });
    await screen.findByText('Costo fijo');

    resolvers['1001']({
      data: {
        breakdown: {
          lines: [{ concepto: 'Cargo por vender', monto: 10, origen: 'api' }],
          neto: 90,
          incompleto: false,
          incomplete_reasons: [],
        },
      },
    });

    // The stale A payload must never appear — B is still selected.
    await waitFor(() => expect(screen.getByText('Costo fijo')).toBeInTheDocument());
    expect(screen.queryByText('Cargo por vender')).not.toBeInTheDocument();
  });

  it('keeps showing the loader when the stale response lands while the newer one is still in flight', async () => {
    // The test above resolves the stale response LAST, when loading is
    // already false, so it cannot fail if the `finally` guard is removed.
    // The guard earns its place in this order instead: the old response
    // arrives while the new request is still pending. Without it, the
    // panel stops saying "Cargando" and renders empty for a sale whose
    // numbers have not arrived — the operator reads absence as an answer.
    const resolvers = {};
    api.get.mockImplementation((url) => {
      const match = url.match(/\/ml-ventas-ops\/orders\/(\d+)/);
      if (match) {
        return new Promise((resolve) => {
          resolvers[match[1]] = resolve;
        });
      }
      return Promise.resolve({ data: {} });
    });

    const { rerender } = render(<DesgloseDrawer orderId={1001} open onClose={vi.fn()} />);
    await waitFor(() => expect(resolvers['1001']).toBeDefined());

    rerender(<DesgloseDrawer orderId={1002} open onClose={vi.fn()} />);
    await waitFor(() => expect(resolvers['1002']).toBeDefined());

    // Only the STALE one answers. B is still in flight.
    resolvers['1001']({
      data: {
        breakdown: {
          lines: [{ concepto: 'Cargo por vender', monto: 10, origen: 'api' }],
          neto: 90,
          incompleto: false,
          incomplete_reasons: [],
        },
      },
    });

    // Flush the stale promise's continuations BEFORE asserting. Without
    // this the assertion finds the loader that was already on screen and
    // passes whether or not the guard exists -- verified by mutation: it
    // stayed green with the `finally` guard removed.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('Cargando desglose…')).toBeInTheDocument();
    expect(screen.queryByText('Cargo por vender')).not.toBeInTheDocument();
  });
});

describe('Focus management', () => {
  it('moves focus into the dialog on open, so the keyboard user is not left behind it', async () => {
    mockBreakdown(1001, { lines: [], neto: null, incompleto: false, incomplete_reasons: [] });
    render(<DesgloseDrawer orderId={1001} open onClose={vi.fn()} />);

    const closeButton = await screen.findByRole('button', { name: /cerrar/i });
    await waitFor(() => expect(closeButton).toHaveFocus());
  });

  it('returns focus to whatever opened it when it closes', async () => {
    mockBreakdown(1001, { lines: [], neto: null, incompleto: false, incomplete_reasons: [] });

    // The Neto button in the listing is what opens this in practice.
    const opener = document.createElement('button');
    opener.textContent = 'abrir';
    document.body.appendChild(opener);
    opener.focus();
    expect(opener).toHaveFocus();

    const { rerender } = render(<DesgloseDrawer orderId={1001} open onClose={vi.fn()} />);
    await waitFor(() => expect(opener).not.toHaveFocus());

    // Closing must not dump the keyboard user at the top of the document:
    // they were reading a row, and that is where they have to come back to.
    rerender(<DesgloseDrawer orderId={1001} open={false} onClose={vi.fn()} />);
    await waitFor(() => expect(opener).toHaveFocus());

    opener.remove();
  });
});

describe('A response with no breakdown', () => {
  it('says so instead of rendering an empty panel', async () => {
    // Blank is the worst of the three states: it looks like a sale that
    // left nothing, which is a number we never received. No loader, no
    // error and no lines used to render exactly that.
    api.get.mockResolvedValue({ data: {} });
    render(<DesgloseDrawer orderId={1001} open onClose={vi.fn()} />);

    expect(
      await screen.findByText('Esta venta todavía no tiene desglose disponible.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Cargando desglose…')).not.toBeInTheDocument();
    expect(screen.queryByText('Error al cargar el desglose.')).not.toBeInTheDocument();
  });
});
