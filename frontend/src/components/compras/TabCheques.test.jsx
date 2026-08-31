/**
 * R11 (compras-cheque-propio-aplicable-a-op): a cheque propio with
 * `orden_pago_id` set is NOT necessarily paid — it may be merely RESERVED
 * against a pendiente OP (INVARIANT R). This test asserts the reserved case
 * never renders a "pagado" label, and instead shows "Reservado en OP N".
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import TabCheques from './TabCheques';

const CHEQUE_RESERVADO = {
  id: 501,
  tipo: 'propio',
  instrumento: 'fisico',
  estado: 'emitido',
  numero: '00000099',
  monto: 12000,
  moneda: 'ARS',
  fecha_emision: '2026-08-20',
  fecha_pago: '2026-08-20',
  banco_empresa_id: 1,
  banco_nombre: 'Banco Nación',
  proveedor_id: 77,
  proveedor_nombre: 'Proveedor SA',
  orden_pago_id: 900,
  // R11 — served by GET /cheques itself. `orden_pago_id` alone cannot tell a
  // reservation from an imputation, so the list endpoint resolves the linked
  // OP's estado; the tab must NOT fetch each OP one at a time to learn it.
  orden_pago_estado: 'pendiente',
  cuit_librador: null,
  librador_nombre: null,
};

const { hookValueCheques, hookValueOP } = vi.hoisted(() => ({
  hookValueCheques: {
    listar: vi.fn().mockResolvedValue({ items: [], total: 0 }),
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
  hookValueOP: {
    listar: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    obtener: vi.fn().mockResolvedValue({ id: 900, estado: 'pendiente' }),
  },
}));

vi.mock('../../hooks/useCheques', () => ({ default: () => hookValueCheques }));
vi.mock('../../hooks/useComprasOP', () => ({ default: () => hookValueOP }));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: () => true }),
}));

describe('TabCheques — R11 reservado no es pagado', () => {
  it('shows "Reservado en OP N", never a paid label, for a linked-but-not-paid cheque', async () => {
    hookValueCheques.listar.mockResolvedValueOnce({ items: [CHEQUE_RESERVADO], total: 1 });

    render(<TabCheques />);

    await waitFor(() => expect(screen.getByText(/Nº 00000099|00000099/)).toBeTruthy());

    await waitFor(() => expect(screen.getByText('Reservado en OP 900')).toBeTruthy());

    // No per-row GET /ordenes-pago/{id}: the estado arrives with the listing.
    expect(hookValueOP.obtener).not.toHaveBeenCalled();

    expect(screen.queryByText(/^Pagado$/i)).toBeNull();
    expect(screen.queryByText(/Aplicado en OP/)).toBeNull();
  });
});
