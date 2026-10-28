import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { aplicarDeshacer, useRecargarAlCerrar } from './historialLogisticaTab';

const LOGISTICAS = [
  { id: 1, nombre: 'Rayo Express', color: '#2563eb' },
  { id: 2, nombre: 'Moto Sur', color: '#16a34a' },
];
const ETIQUETAS = [
  { shipping_id: 'A', logistica_id: 1, logistica_nombre: 'Rayo Express', logistica_color: '#2563eb' },
  { shipping_id: 'B', logistica_id: 1, logistica_nombre: 'Rayo Express', logistica_color: '#2563eb' },
];

describe('aplicarDeshacer', () => {
  it('patches only the undone label, with name and color from the logísticas list', () => {
    const result = aplicarDeshacer(ETIQUETAS, 'A', 2, LOGISTICAS);
    expect(result[0]).toEqual({
      shipping_id: 'A',
      logistica_id: 2,
      logistica_nombre: 'Moto Sur',
      logistica_color: '#16a34a',
    });
    expect(result[1]).toBe(ETIQUETAS[1]);
  });

  it('leaves name and color empty when the label goes back to no logística', () => {
    const [fila] = aplicarDeshacer(ETIQUETAS, 'A', null, LOGISTICAS);
    expect(fila).toMatchObject({ logistica_id: null, logistica_nombre: null, logistica_color: null });
  });
});

describe('useRecargarAlCerrar', () => {
  it('reloads once when the modal closes, not while it is open or never opened', () => {
    const recargar = vi.fn();
    const { rerender } = renderHook(({ abierto }) => useRecargarAlCerrar(abierto, recargar), {
      initialProps: { abierto: false },
    });
    expect(recargar).not.toHaveBeenCalled();

    rerender({ abierto: true });
    expect(recargar).not.toHaveBeenCalled();

    rerender({ abierto: false });
    expect(recargar).toHaveBeenCalledTimes(1);

    rerender({ abierto: false });
    expect(recargar).toHaveBeenCalledTimes(1);
  });
});
