import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import useComprasPedidos from './useComprasPedidos';
import api from '../services/api';

vi.mock('../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

describe('useComprasPedidos — cuenta corriente', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('marcarCuentaCorriente posts to the mark endpoint and returns the updated pedido', async () => {
    api.post.mockResolvedValue({
      data: { id: 1, estado: 'en_cuenta_corriente', op_cuenta_corriente_id: 5 },
    });

    const { result } = renderHook(() => useComprasPedidos());

    let response;
    await act(async () => {
      response = await result.current.marcarCuentaCorriente(1);
    });

    expect(api.post).toHaveBeenCalledWith(
      '/administracion/compras/pedidos/1/cuenta-corriente'
    );
    expect(response).toEqual({ id: 1, estado: 'en_cuenta_corriente', op_cuenta_corriente_id: 5 });
    expect(result.current.error).toBeNull();
  });

  it('marcarCuentaCorriente surfaces backend error detail via wrap()', async () => {
    api.post.mockRejectedValue({ response: { data: { detail: 'Estado inválido para marcar.' } } });

    const { result } = renderHook(() => useComprasPedidos());

    await act(async () => {
      await expect(result.current.marcarCuentaCorriente(1)).rejects.toBeTruthy();
    });

    await waitFor(() => expect(result.current.error).toBe('Estado inválido para marcar.'));
  });

  it('revertirCuentaCorriente posts motivo to the revertir endpoint', async () => {
    api.post.mockResolvedValue({
      data: { id: 1, estado: 'aprobado', op_cuenta_corriente_id: null },
    });

    const { result } = renderHook(() => useComprasPedidos());

    let response;
    await act(async () => {
      response = await result.current.revertirCuentaCorriente(1, 'Error de carga');
    });

    expect(api.post).toHaveBeenCalledWith(
      '/administracion/compras/pedidos/1/cuenta-corriente/revertir',
      { motivo: 'Error de carga' }
    );
    expect(response).toEqual({ id: 1, estado: 'aprobado', op_cuenta_corriente_id: null });
  });

  it('revertirCuentaCorriente surfaces fail-closed 409 (e.g. ingreso ya registrado)', async () => {
    api.post.mockRejectedValue({
      response: { data: { detail: 'No se puede revertir: ya existen ingresos registrados.' } },
    });

    const { result } = renderHook(() => useComprasPedidos());

    await act(async () => {
      await expect(result.current.revertirCuentaCorriente(1, 'motivo')).rejects.toBeTruthy();
    });

    await waitFor(() =>
      expect(result.current.error).toBe('No se puede revertir: ya existen ingresos registrados.')
    );
  });
});
