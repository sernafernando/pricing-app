/**
 * The two "apply a cheque propio to an OP" entry points deliberately do NOT
 * share a backend route. This pins that difference so a future "unification"
 * fails loudly instead of silently breaking one of them.
 *
 *   TabCheques   → the OP already exists and is `pendiente`, so it has an id:
 *                  it RESERVES via POST /ordenes-pago/{op_id}/cheques
 *                  (useCheques.reservarEnOp).
 *   PanelCheques → lives inside ModalOrdenPagoNueva, where the OP may not
 *                  exist yet: there is no `op_id` to reserve against, so the
 *                  cheque travels in the OP's own `cheques` payload and the
 *                  panel calls NO endpoint at all.
 *
 * Fails if PanelCheques starts calling the reserve endpoint, or if TabCheques
 * stops calling it.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TabCheques from './TabCheques';
import PanelCheques from './_shared/PanelCheques';

const CHEQUE_LIBRE = {
  id: 77,
  tipo: 'propio',
  instrumento: 'fisico',
  estado: 'emitido',
  numero: '00000123',
  monto: 5000,
  moneda: 'ARS',
  fecha_emision: '2026-08-20',
  fecha_pago: '2026-08-20',
  banco_empresa_id: 1,
  banco_nombre: 'Banco Nación',
  proveedor_id: 42,
  proveedor_nombre: 'Proveedor SA',
  orden_pago_id: null,
  orden_pago_estado: null,
  cuit_librador: null,
  librador_nombre: null,
};

const OP_PENDIENTE = { id: 900, estado: 'pendiente', monto_total: 5000, moneda: 'ARS' };

const { hookValueCheques, hookValueOP, hookValueAplicables } = vi.hoisted(() => ({
  hookValueCheques: {
    listar: vi.fn(),
    anular: vi.fn(),
    transicionarEcheq: vi.fn(),
    debitar: vi.fn(),
    depositar: vi.fn(),
    acreditar: vi.fn(),
    obtenerReporte: vi.fn(),
    reservarEnOp: vi.fn(),
    liberarDeOp: vi.fn(),
    loading: false,
    error: null,
  },
  hookValueOP: { listar: vi.fn(), obtener: vi.fn() },
  hookValueAplicables: { fetchElegibles: vi.fn(), loading: false },
}));

vi.mock('../../hooks/useCheques', () => ({ default: () => hookValueCheques }));
vi.mock('../../hooks/useComprasOP', () => ({ default: () => hookValueOP }));
vi.mock('../../hooks/useChequesAplicables', () => ({ default: () => hookValueAplicables }));
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: () => true }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  hookValueCheques.listar.mockResolvedValue({ items: [], total: 0 });
  hookValueCheques.reservarEnOp.mockResolvedValue({ ok: true });
  hookValueOP.listar.mockResolvedValue({ items: [OP_PENDIENTE], total: 1 });
  hookValueOP.obtener.mockResolvedValue(OP_PENDIENTE);
  hookValueAplicables.fetchElegibles.mockResolvedValue([CHEQUE_LIBRE]);
});

describe('cheque propio → OP: two entry points, one reserve endpoint', () => {
  it('TabCheques reserves against the EXISTING OP via reservarEnOp', async () => {
    const user = userEvent.setup();
    hookValueCheques.listar.mockResolvedValue({ items: [CHEQUE_LIBRE], total: 1 });

    render(<TabCheques />);

    const aplicar = await screen.findByLabelText(
      `Aplicar cheque ${CHEQUE_LIBRE.numero} a una orden de pago`,
    );
    await user.click(aplicar);

    const opRow = await screen.findByLabelText(`Aplicar cheque a la OP ${OP_PENDIENTE.id}`);
    await user.click(opRow);

    await waitFor(() =>
      expect(hookValueCheques.reservarEnOp).toHaveBeenCalledWith(OP_PENDIENTE.id, {
        cheque_id: CHEQUE_LIBRE.id,
        monto: CHEQUE_LIBRE.monto,
        moneda: CHEQUE_LIBRE.moneda,
      }),
    );
  });

  it('PanelCheques never reserves — the cheque travels in the OP payload', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(<PanelCheques proveedorId={42} empresaId={1} opMoneda="ARS" onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: /^Cheques/ }));
    await user.click(screen.getByRole('button', { name: /Aplicar cheque propio/ }));

    const chequeRow = await screen.findByLabelText(`Aplicar cheque propio ${CHEQUE_LIBRE.numero}`);
    await user.click(chequeRow);

    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith([
        expect.objectContaining({
          cheque_id: CHEQUE_LIBRE.id,
          monto: CHEQUE_LIBRE.monto,
          moneda: CHEQUE_LIBRE.moneda,
          _es_aplicado_propio: true,
        }),
      ]),
    );

    // There is no op_id yet: reserving is impossible, so no endpoint is hit.
    expect(hookValueCheques.reservarEnOp).not.toHaveBeenCalled();
    expect(hookValueOP.listar).not.toHaveBeenCalled();
  });
});
