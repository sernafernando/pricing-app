import { describe, it, expect, vi, beforeEach } from 'vitest';

// Same approach as api.tickets.test.js: unmock the real module and mock axios
// directly so we assert the REAL request wiring (URL + body shape), not a
// mocked API client — per obs #1350's "stray required field" lesson (PR 4b's
// `pages: int` bug was invisible to tests that mocked the service layer).
vi.unmock('../services/api');

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockUse = vi.fn();

vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: mockGet,
      post: mockPost,
      interceptors: {
        request: { use: mockUse },
        response: { use: mockUse },
      },
    }),
  },
}));

describe('propuestasAPI request wiring', () => {
  beforeEach(() => {
    vi.resetModules();
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it('confirmar posts to the single-confirm route with no body', async () => {
    const { propuestasAPI } = await import('./api');
    propuestasAPI.confirmar(7);
    expect(mockPost).toHaveBeenCalledWith('/tickets/propuestas/7/confirmar');
    // Regression guard: no stray second argument (not even `undefined`) —
    // ratification must stay byte-identical to today's request shape.
    expect(mockPost.mock.calls[0]).toHaveLength(1);
  });

  it('confirmar sends the corrected value as {valor_corregido} when provided (PR2)', async () => {
    const { propuestasAPI } = await import('./api');
    propuestasAPI.confirmar(7, 'menor');
    expect(mockPost).toHaveBeenCalledWith('/tickets/propuestas/7/confirmar', {
      valor_corregido: 'menor',
    });
    // Regression guard for the PR 4b class of bug (obs #1350): no stray
    // extra keys beyond the one the backend's `ConfirmarRequest` accepts.
    expect(Object.keys(mockPost.mock.calls[0][1])).toEqual(['valor_corregido']);
  });

  it('descartar posts to the single-discard route with no body', async () => {
    const { propuestasAPI } = await import('./api');
    propuestasAPI.descartar(7);
    expect(mockPost).toHaveBeenCalledWith('/tickets/propuestas/7/descartar');
  });

  it('confirmarBatch sends exactly {propuesta_ids: [...]} — the exact shape the backend requires', async () => {
    const { propuestasAPI } = await import('./api');
    propuestasAPI.confirmarBatch([3, 5, 9]);
    expect(mockPost).toHaveBeenCalledWith('/tickets/propuestas/confirmar-batch', {
      propuesta_ids: [3, 5, 9],
    });
    // Regression guard for the PR 4b class of bug: no stray extra keys.
    expect(Object.keys(mockPost.mock.calls[0][1])).toEqual(['propuesta_ids']);
  });

  it('ticketsAPI.listarPropuestas gets the ticket-scoped propuestas route', async () => {
    const { ticketsAPI } = await import('./api');
    ticketsAPI.listarPropuestas(42);
    expect(mockGet).toHaveBeenCalledWith('/tickets/tickets/42/propuestas');
  });

  it('ticketsAPI.triage posts with forzar as a query param, defaulting to false', async () => {
    const { ticketsAPI } = await import('./api');
    ticketsAPI.triage(42);
    expect(mockPost).toHaveBeenCalledWith('/tickets/tickets/42/triage', null, {
      params: { forzar: false },
    });

    ticketsAPI.triage(42, true);
    expect(mockPost).toHaveBeenCalledWith('/tickets/tickets/42/triage', null, {
      params: { forzar: true },
    });
  });
});
