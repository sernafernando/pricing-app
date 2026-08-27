/**
 * ModalOrdenPagoNueva — the NC amount must be ONE number.
 *
 * Reported bug: "las NCs en USD no funcionan, no restan". A USD NC applied to
 * an ARS OP with no `tipo_cambio` was silently dropped from the per-item
 * deduction (the total never went down) while the summary row happily showed a
 * discount computed through a DIFFERENT chain — one that, with no TC at all,
 * added the USD figure straight into the ARS total.
 *
 * These tests pin the three properties that fix demands:
 *   1. the NC's own `tipo_cambio` actually deducts,
 *   2. the summary row and the "Total a pagar" agree on the same number,
 *   3. a cross-currency NC with no resolvable TC is reported, never vanished.
 *
 * NOTE: vite.config.js sets `css: false`, so CSS Module class names do not
 * resolve — assert on text and roles only, never on className.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ModalOrdenPagoNueva from './ModalOrdenPagoNueva';

const { apiMock, opApi } = vi.hoisted(() => ({
  apiMock: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  opApi: {
    loading: false,
    error: null,
    listar: vi.fn(),
    obtener: vi.fn(),
    crear: vi.fn(),
    crearYPagar: vi.fn(),
    editar: vi.fn(),
    cancelarPendiente: vi.fn(),
    pagar: vi.fn(),
    anular: vi.fn(),
    distribuirAutomatico: vi.fn(),
    eliminar: vi.fn(),
    aplicarNC: vi.fn(),
  },
}));

vi.mock('../../services/api', () => ({ default: apiMock }));
vi.mock('../../hooks/useComprasOP', () => ({ default: () => opApi }));
vi.mock('../../store/authStore', () => ({
  useAuthStore: (selector) => selector({ user: { id: 1, nombre: 'Test' } }),
}));
vi.mock('./ProveedorComprasAutocomplete', () => ({ default: () => null }));
vi.mock('./_shared/PanelCheques', () => ({ default: () => null }));

// The NC panel is replaced by a button that emits a fixed selection, so these
// tests exercise ModalOrdenPagoNueva's own math instead of the panel's UI.
// `ncsAEmitir` is read at click time so each test can set its own payload.
const { panelState } = vi.hoisted(() => ({ panelState: { ncsAEmitir: [] } }));
vi.mock('./_shared/PanelNCsProveedor', () => ({
  default: ({ onChange }) => (
    <button type="button" onClick={() => onChange(panelState.ncsAEmitir)}>
      emitir-ncs
    </button>
  ),
}));

const PEDIDO_ARS = {
  id: 101,
  numero: 'PC-2026-00101',
  empresa_id: 1,
  proveedor_id: 10,
  moneda: 'ARS',
  monto: '20000',
  saldo_pendiente: '20000',
  tipo_cambio: null,
  numero_factura: null,
};

const renderModal = () =>
  render(
    <ModalOrdenPagoNueva
      empresas={[{ id: 1, nombre: 'Empresa Test' }]}
      onClose={vi.fn()}
      pedidoInicial={PEDIDO_ARS}
      pendientesDelProveedor={[PEDIDO_ARS]}
    />,
  );

// "Total a pagar" is the number the user reads; the same formatted amount also
// appears in the pedido row and the summary breakdown, so scope the lookup to
// the total's own label instead of matching text across the whole modal.
const totalAPagar = () => screen.getByText('Total a pagar').nextElementSibling.textContent;

const aplicarNCs = async (user, ncs) => {
  panelState.ncsAEmitir = ncs;
  await user.click(screen.getByRole('button', { name: 'emitir-ncs' }));
};

describe('ModalOrdenPagoNueva — NCs cross-moneda', () => {
  beforeEach(() => {
    apiMock.get.mockReset().mockResolvedValue({ data: [] });
    panelState.ncsAEmitir = [];
  });

  it('deduce una NC en USD usando el TC propio de la NC cuando la OP no tiene TC', async () => {
    // The reported bug: this OP has no tipo_cambio, so before the fix the USD
    // NC was skipped and "Total a pagar" stayed at the gross 20.000.
    const user = userEvent.setup();
    renderModal();

    await waitFor(() => expect(totalAPagar()).toBe('$20.000,00'));

    await aplicarNCs(user, [
      { nc_id: 5, monto: 10, moneda: 'USD', tipo_cambio: '1450', pedido_id: 101 },
    ]);

    // 20.000 − (10 USD × 1450) = 5.500 ARS
    await waitFor(() => expect(totalAPagar()).toBe('$5.500,00'));
  });

  it('el renglón del resumen muestra exactamente lo que descontó el total', async () => {
    const user = userEvent.setup();
    renderModal();
    await waitFor(() => expect(totalAPagar()).toBe('$20.000,00'));

    await aplicarNCs(user, [
      { nc_id: 5, monto: 10, moneda: 'USD', tipo_cambio: '1450', pedido_id: 101 },
    ]);

    await waitFor(() => expect(screen.getByText('Notas de crédito')).toBeInTheDocument());
    // Summary line and the real deduction are the same 14.500, not two numbers.
    expect(screen.getByText('-$14.500,00')).toBeInTheDocument();
    expect(totalAPagar()).toBe('$5.500,00');
  });

  it('el TC por NC gana sobre el TC propio de la NC', async () => {
    const user = userEvent.setup();
    renderModal();
    await waitFor(() => expect(totalAPagar()).toBe('$20.000,00'));

    await aplicarNCs(user, [
      {
        nc_id: 5,
        monto: 10,
        moneda: 'USD',
        tipo_cambio: '1450',
        tipo_cambio_override: 1500,
        pedido_id: 101,
      },
    ]);

    // 20.000 − (10 USD × 1500) = 5.000 ARS
    await waitFor(() => expect(screen.getByText('-$15.000,00')).toBeInTheDocument());
    expect(totalAPagar()).toBe('$5.000,00');
  });

  it('avisa cuando una NC cross-moneda no tiene TC en ningún lado, en vez de desaparecer', async () => {
    const user = userEvent.setup();
    renderModal();
    await waitFor(() => expect(totalAPagar()).toBe('$20.000,00'));

    await aplicarNCs(user, [
      { nc_id: 5, monto: 10, moneda: 'USD', tipo_cambio: null, pedido_id: 101 },
    ]);

    await waitFor(() => {
      expect(screen.getByText(/no se está descontando/i)).toBeInTheDocument();
    });
    // And no fabricated discount: the total stays at the gross amount.
    expect(totalAPagar()).toBe('$20.000,00');
    expect(screen.queryByText('Notas de crédito')).not.toBeInTheDocument();
  });
});
