import { describe, it, expect, vi, beforeEach } from 'vitest';

// setup.js globally mocks '../services/api' with plain vi.fn() stubs (needed
// by page-level tests). This suite verifies the REAL implementation's request
// wiring, so it unmocks the module and mocks axios directly instead — same
// approach as `api.promociones.test.js`.
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

describe('pxqAPI.sync cannot ask ML to clear the live tier array', () => {
  beforeEach(() => {
    vi.resetModules();
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it('always posts allow_clear: false', async () => {
    const { pxqAPI } = await import('./api');
    pxqAPI.sync('MLA001');
    expect(mockPost).toHaveBeenCalledWith('/pxq/MLA001/sync', { allow_clear: false });
  });

  // The incident this guards: `POST /items/{id}/prices/standard/quantity`
  // REPLACES the whole tier array, so `allow_clear: true` deletes every live
  // tier on the publication. It used to be reachable as the second argument of
  // this very verb, and the UI sent it whenever the local mirror was empty.
  // A wipe is a destructive operation that needs its own explicitly-labelled
  // verb; it must not be expressible as an argument to "sincronizar".
  it('ignores a caller that still tries to pass a clear flag', async () => {
    const { pxqAPI } = await import('./api');
    pxqAPI.sync('MLA001', true);
    expect(mockPost).toHaveBeenCalledWith('/pxq/MLA001/sync', { allow_clear: false });
  });

  it('never emits allow_clear: true for any argument shape', async () => {
    const { pxqAPI } = await import('./api');
    pxqAPI.sync('MLA001');
    pxqAPI.sync('MLA002', true);
    pxqAPI.sync('MLA003', { allow_clear: true });

    expect(mockPost).toHaveBeenCalledTimes(3);
    for (const [, body] of mockPost.mock.calls) {
      expect(body.allow_clear).toBe(false);
    }
  });
});

describe('pxqAPI.adoptLive imports live tiers and can express nothing else', () => {
  beforeEach(() => {
    vi.resetModules();
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it('posts to the adopt-live path for the given item', async () => {
    const { pxqAPI } = await import('./api');
    pxqAPI.adoptLive('MLA001');
    expect(mockPost).toHaveBeenCalledWith('/pxq/MLA001/adopt-live');
  });

  // The backend endpoint takes NO request body. Sending one would be the first
  // step of the drift that gave `sync` an `allow_clear` argument: a body is a
  // place to put an option, and an import verb has no option worth having.
  it('sends no request body at all', async () => {
    const { pxqAPI } = await import('./api');
    pxqAPI.adoptLive('MLA001');
    expect(mockPost.mock.calls[0]).toHaveLength(1);
  });

  it('ignores anything a caller tries to pass beyond the item id', async () => {
    const { pxqAPI } = await import('./api');
    pxqAPI.adoptLive('MLA001', { overwrite: true });
    pxqAPI.adoptLive('MLA002', true);

    expect(mockPost).toHaveBeenCalledTimes(2);
    for (const call of mockPost.mock.calls) {
      expect(call).toHaveLength(1);
    }
  });

  // Import-only means import-only: no path through this verb may reach the
  // sync endpoint, which is the one that replaces the whole live array.
  it('never touches the sync endpoint', async () => {
    const { pxqAPI } = await import('./api');
    pxqAPI.adoptLive('MLA001');
    for (const [url] of mockPost.mock.calls) {
      expect(url).not.toMatch(/\/sync$/);
    }
  });
});
