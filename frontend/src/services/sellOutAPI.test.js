import { describe, it, expect, beforeEach, vi } from 'vitest';
import api from './api';
import { sellOutAPI } from './sellOutAPI';

describe('sellOutAPI', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('approves a campaign loaded on its own (tacticals approval S6)', () => {
    sellOutAPI.aprobar(7);
    expect(api.post).toHaveBeenCalledWith('/sell-out/campanas/7/aprobar');
  });

  it('still voids with the trimmed reason (previous behaviour)', () => {
    sellOutAPI.anular(7, '  repetida ');
    expect(api.post).toHaveBeenCalledWith('/sell-out/campanas/7/anular', { motivo: 'repetida' });
  });
});
