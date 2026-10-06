import { describe, it, expect, vi, beforeEach } from 'vitest';
import api from '../services/api';
import { useTiendasOficialesStore } from './tiendasOficialesStore';

const row = (nombre) => [{ store_id: 1, nombre, clave: null, orden: 0, activa: true }];

beforeEach(() => {
  vi.clearAllMocks();
  useTiendasOficialesStore.setState({ tiendas: [], loaded: false, loading: false });
});

describe('tiendasOficialesStore', () => {
  it('a forced reload wins over an older request that resolves later', async () => {
    let resolveOld;
    api.get.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    api.get.mockImplementationOnce(() => Promise.resolve({ data: row('nuevo') }));

    const first = useTiendasOficialesStore.getState().load();
    const second = useTiendasOficialesStore.getState().load(true);
    await second;
    resolveOld({ data: row('viejo') });
    await first;

    expect(useTiendasOficialesStore.getState().tiendas[0].nombre).toBe('nuevo');
  });
});
