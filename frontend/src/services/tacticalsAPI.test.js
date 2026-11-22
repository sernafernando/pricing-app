import { describe, it, expect, beforeEach, vi } from 'vitest';
import api from './api';
import { tacticalsAPI } from './tacticalsAPI';

describe('tacticalsAPI', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('approves a pending tactical (tacticals approval S3)', () => {
    tacticalsAPI.aprobar(12);
    expect(api.post).toHaveBeenCalledWith('/tacticals/12/aprobar');
  });

  it('still voids with the reason (previous behaviour)', () => {
    tacticalsAPI.anular(12, 'Sin acuerdo');
    expect(api.post).toHaveBeenCalledWith('/tacticals/12/anular', { motivo: 'Sin acuerdo' });
  });

  it('lists the pending ones with the same params', () => {
    tacticalsAPI.listar({ estado: 'pendientes_aprobacion', page: 1 });
    expect(api.get).toHaveBeenCalledWith('/tacticals', { params: { estado: 'pendientes_aprobacion', page: 1 } });
  });
});
