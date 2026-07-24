import { describe, it, expect, vi, beforeEach } from 'vitest';

// setup.js globally mocks '../services/api' with plain vi.fn() stubs (needed
// by page-level tests). This suite verifies the REAL implementation's URL
// wiring, so it unmocks the module and mocks axios directly instead (mirrors
// api.promociones.test.js).
vi.unmock('../services/api');

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockDelete = vi.fn();
const mockUse = vi.fn();

vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: mockGet,
      post: mockPost,
      delete: mockDelete,
      interceptors: {
        request: { use: mockUse },
        response: { use: mockUse },
      },
    }),
  },
}));

describe('marcasPmAPI (sub-pm-scope-marcas PR3)', () => {
  beforeEach(() => {
    vi.resetModules();
    mockGet.mockReset();
    mockPost.mockReset();
    mockDelete.mockReset();
  });

  it('misTitularidades calls GET /marcas-pm/mis-titularidades', async () => {
    const { marcasPmAPI } = await import('./api');
    marcasPmAPI.misTitularidades();
    expect(mockGet).toHaveBeenCalledWith('/marcas-pm/mis-titularidades');
  });

  it('listarSubPMs calls GET /marcas-pm/sub-pms with marca/categoria params', async () => {
    const { marcasPmAPI } = await import('./api');
    marcasPmAPI.listarSubPMs('Samsung', 'Celulares');
    expect(mockGet).toHaveBeenCalledWith('/marcas-pm/sub-pms', {
      params: { marca: 'Samsung', categoria: 'Celulares' },
    });
  });

  it('crearSubPM calls POST /marcas-pm/sub-pms with the grant payload', async () => {
    const { marcasPmAPI } = await import('./api');
    const payload = { marca: 'Samsung', categoria: 'Celulares', usuario_id: 7 };
    marcasPmAPI.crearSubPM(payload);
    expect(mockPost).toHaveBeenCalledWith('/marcas-pm/sub-pms', payload);
  });

  it('eliminarSubPM calls DELETE /marcas-pm/sub-pms/{id}', async () => {
    const { marcasPmAPI } = await import('./api');
    marcasPmAPI.eliminarSubPM(42);
    expect(mockDelete).toHaveBeenCalledWith('/marcas-pm/sub-pms/42');
  });

  it('listarUsuariosPM calls GET /usuarios/pms (non-admin-safe picker source)', async () => {
    const { marcasPmAPI } = await import('./api');
    marcasPmAPI.listarUsuariosPM();
    expect(mockGet).toHaveBeenCalledWith('/usuarios/pms');
  });
});
