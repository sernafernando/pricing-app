import { describe, it, expect, vi, beforeEach } from 'vitest';

// setup.js globally mocks '../services/api' with plain vi.fn() stubs (needed
// by page-level tests). This suite verifies the REAL implementation's request
// wiring, so it unmocks the module and mocks axios directly instead — same
// approach as `api.pxq.test.js` / `api.promociones.test.js`.
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

describe('ticketsAPI.marcarRevisado calls the real double-segment route', () => {
  beforeEach(() => {
    vi.resetModules();
    mockGet.mockReset();
    mockPost.mockReset();
  });

  // Regression guard for the bug fixed in this PR: the route is registered as
  // `/tickets/marcar-revisado/{id}` inside the tickets router, and main.py
  // mounts that whole router under the `/api/tickets` prefix — so the real
  // path needs the `/tickets` segment TWICE. A single-segment call 404s
  // server-side and was previously swallowed silently by TicketDetail's
  // non-blocking catch, so the badge counters never cleared.
  it('posts to the double-segment path, not the single-segment one', async () => {
    const { ticketsAPI } = await import('./api');
    ticketsAPI.marcarRevisado(42);
    expect(mockPost).toHaveBeenCalledWith('/tickets/tickets/marcar-revisado/42');
    expect(mockPost).not.toHaveBeenCalledWith('/tickets/marcar-revisado/42');
  });
});
