import { describe, it, expect } from 'vitest';
import { resolverDestinoItemId, requiereDestino } from './destinoValores';

const UN_PEDIDO = ['101'];
const DOS_PEDIDOS = ['101', '202'];

describe('resolverDestinoItemId', () => {
  it('infiere el único pedido cuando el valor no trae destino', () => {
    expect(resolverDestinoItemId({ pedido_id: null }, UN_PEDIDO, true)).toBe('101');
  });

  it('NO infiere nada con varios pedidos: sin destino explícito no descuenta', () => {
    expect(resolverDestinoItemId({ pedido_id: null }, DOS_PEDIDOS, false)).toBeNull();
  });

  it('respeta el destino explícito', () => {
    expect(resolverDestinoItemId({ pedido_id: 202 }, DOS_PEDIDOS, false)).toBe('202');
  });

  it('acepta el destino como number o como string', () => {
    expect(resolverDestinoItemId({ pedido_id: 202 }, DOS_PEDIDOS, false)).toBe('202');
    expect(resolverDestinoItemId({ pedido_id: '202' }, DOS_PEDIDOS, false)).toBe('202');
  });

  it('descarta un destino que no está en la OP', () => {
    // El pedido salió de la OP pero el valor quedó apuntando ahí: descontarlo
    // sería restar de un ítem que no existe, y mandarlo al backend es un 422.
    expect(resolverDestinoItemId({ pedido_id: 999 }, DOS_PEDIDOS, false)).toBeNull();
  });

  it('un destino explícito gana sobre la inferencia, aun con un solo pedido', () => {
    expect(resolverDestinoItemId({ pedido_id: 999 }, UN_PEDIDO, true)).toBeNull();
  });

  it('sin pedidos en la OP no hay destino que resolver', () => {
    expect(resolverDestinoItemId({ pedido_id: null }, [], false)).toBeNull();
  });

  it('tolera un valor sin la clave pedido_id', () => {
    expect(resolverDestinoItemId({}, UN_PEDIDO, true)).toBe('101');
  });
});

describe('requiereDestino', () => {
  it('una OP a cuenta no exige destino', () => {
    expect(requiereDestino([])).toBe(false);
  });

  it('una OP que imputa pedidos sí', () => {
    expect(requiereDestino(UN_PEDIDO)).toBe(true);
    expect(requiereDestino(DOS_PEDIDOS)).toBe(true);
  });
});
