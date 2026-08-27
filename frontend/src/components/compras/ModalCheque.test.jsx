/**
 * ModalCheque mode="op" renders its own <form id="form-cheque"> INSIDE
 * ModalOrdenPagoNueva's parent <form onSubmit={...}> (PanelCheques is
 * rendered within it). Submitting the inner cheque form bubbles a `submit`
 * event to the parent form unless it is stopped — without stopping it, the
 * OP form also submits, closing the OP modal and losing the cheque.
 *
 * This test mounts ModalCheque nested inside a parent <form> with a spy
 * submit handler, fires the inner form's submit event directly (bypassing
 * the browser's own required-field constraint validation, which would
 * otherwise mask whatever handleSubmit itself does), and asserts the
 * parent handler is never invoked.
 *
 * NOTE on the mock below: the `useCheques` mock MUST return the exact same
 * object/function references on every call — `vi.hoisted` gives us that.
 * A naive `default: () => ({ ... vi.fn() ... })` factory hands ModalCheque a
 * BRAND NEW `listarChequeras` reference on every render, which breaks the
 * `useCallback([listarChequeras])` memoization inside ModalCheque and sends
 * its "reset chequera on bancoEmpresaId change" effect into an infinite
 * render loop (it calls `setChequeras([])` with a fresh array identity every
 * time, which re-triggers the effect since its dependency also changed).
 * This is a test-mock pitfall, not a bug in ModalCheque itself — the real
 * `useCheques` hook memoizes with `useCallback` and is stable across renders.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import ModalCheque from './ModalCheque';

const { hookValue } = vi.hoisted(() => ({
  hookValue: {
    emitirPropio: vi.fn(),
    recibirTercero: vi.fn(),
    listarChequeras: vi.fn().mockResolvedValue({ items: [] }),
    loading: false,
    error: null,
  },
}));

vi.mock('../../hooks/useCheques', () => ({ default: () => hookValue }));

vi.mock('./ProveedorComprasAutocomplete', () => ({
  default: () => <div data-testid="proveedor-stub" />,
}));

vi.mock('./_shared/FormChequera', () => ({
  default: () => <div data-testid="form-chequera-stub" />,
}));

describe('ModalCheque — mode="op" nested inside a parent OP form', () => {
  it('does NOT bubble submit to the parent form (stopPropagation)', () => {
    const onSubmitPadre = vi.fn((e) => e.preventDefault());
    const onEmitido = vi.fn();

    const { container } = render(
      <form onSubmit={onSubmitPadre}>
        <ModalCheque
          mode="op"
          proveedorId={10}
          empresaId={1}
          onClose={vi.fn()}
          onEmitido={onEmitido}
        />
      </form>,
    );

    const innerForm = container.querySelector('#form-cheque');
    expect(innerForm).not.toBeNull();

    fireEvent.submit(innerForm);

    expect(onSubmitPadre).not.toHaveBeenCalled();
  });
});
