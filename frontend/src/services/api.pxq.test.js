import { describe, it, expect, vi, beforeEach } from 'vitest';

// setup.js globally mocks '../services/api' with plain vi.fn() stubs (needed
// by page-level tests). This suite verifies the REAL implementation's request
// wiring, so it unmocks the module and mocks axios directly instead — same
// approach as `api.promociones.test.js`.
vi.unmock('../services/api');

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockUse = vi.fn();
// Captured, not stubbed: the response interceptor is the unit under test in
// the `error contract` suite below, so the mock has to hand it back rather than
// swallow it like `mockUse` does for the request side.
const responseInterceptors = [];

vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: mockGet,
      post: mockPost,
      interceptors: {
        request: { use: mockUse },
        response: {
          use: (onFulfilled, onRejected) => responseInterceptors.push({ onFulfilled, onRejected }),
        },
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

/**
 * The response interceptor, exercised for real.
 *
 * This suite exists because of a defect that shipped twice. `PxqPanel` reads
 * `detail.status` to pick its message, and `PxqPanel.test.jsx` proves it does —
 * but that file does `vi.mock('../../services/api', ...)`, replacing the whole
 * module, so the interceptor never runs there and the tests hand the component
 * a `detail` object by hand. The interceptor was meanwhile flattening every
 * object `detail` to a string, so in production `detail.status` was always
 * `undefined` and the `adopt_conflict` / `divergence` branches were dead code
 * behind green tests.
 *
 * Anything that asserts on the SHAPE of an error payload belongs here, where
 * the real module runs.
 */
describe('response interceptor — typed error contracts vs. renderable strings', () => {
  beforeEach(() => {
    vi.resetModules();
    responseInterceptors.length = 0;
    mockGet.mockReset();
    mockPost.mockReset();
  });

  /**
   * Pushes `response` through the REAL registered interceptor and returns the
   * `data` a component would end up reading. Also asserts the interceptor
   * still rejects with the same error object — normalizing a payload must
   * never turn a failure into a success.
   */
  async function throughInterceptor(response) {
    await import('./api');
    const { onRejected } = responseInterceptors[responseInterceptors.length - 1];
    const error = { config: { url: '/pxq/MLA001/adopt-live' }, response };
    await expect(onRejected(error)).rejects.toBe(error);
    return error.response.data;
  }

  // --- typed application errors survive ------------------------------------

  // The wire shape is NOT `{detail: {...}}`. `backend/app/core/exceptions.py`'s
  // `http_exception_handler` (registered on `StarletteHTTPException` in
  // `main.py`) returns a dict `detail` with no `code` key AS THE ROOT of the
  // body. Verified against the real handler, not assumed.
  it('surfaces the adopt-live 409 payload the backend actually puts on the wire', async () => {
    const data = await throughInterceptor({
      status: 409,
      data: {
        status: 'adopt_conflict',
        reason: 'The local mirror already has tiers for this publication',
        conflicts: [
          { tier_id: 3, cantidad_minima: 12 },
          { tier_id: 7, cantidad_minima: 24 },
        ],
      },
    });

    expect(typeof data.detail).toBe('object');
    expect(data.detail.status).toBe('adopt_conflict');
    // The conflicting rows are the entire reason the backend sends a structured
    // payload: without them the refusal cannot name what to delete.
    expect(data.detail.conflicts).toEqual([
      { tier_id: 3, cantidad_minima: 12 },
      { tier_id: 7, cantidad_minima: 24 },
    ]);
  });

  // The lift must not create `data.detail = data`, or every logger and every
  // `JSON.stringify(response.data)` in the app blows up on a cycle.
  it('leaves the payload serializable (no circular reference)', async () => {
    const data = await throughInterceptor({
      status: 409,
      data: { status: 'adopt_conflict', reason: 'x', conflicts: [] },
    });

    expect(() => JSON.stringify(data)).not.toThrow();
  });

  it('leaves a nested typed detail untouched', async () => {
    const data = await throughInterceptor({
      status: 409,
      data: {
        detail: {
          status: 'adopt_conflict',
          reason: 'The local mirror already has tiers',
          conflicts: [{ tier_id: 3, cantidad_minima: 12 }],
        },
      },
    });

    expect(data.detail.status).toBe('adopt_conflict');
    expect(data.detail.conflicts).toEqual([{ tier_id: 3, cantidad_minima: 12 }]);
  });

  it('preserves the 503 adopt_read_unavailable status and reason', async () => {
    const data = await throughInterceptor({
      status: 503,
      data: {
        status: 'adopt_read_unavailable',
        reason: 'the live read failed; nothing was imported',
      },
    });

    expect(data.detail.status).toBe('adopt_read_unavailable');
    expect(data.detail.reason).toMatch(/nothing was imported/);
  });

  // The SECOND victim of the same flattening. `PxqSyncControl` renders its
  // divergence banner only when `detail.divergences` is an array; a flattened
  // string has no `divergences`, so that banner had never rendered either.
  it('preserves the sync 409 divergences array that the banner renders', async () => {
    const data = await throughInterceptor({
      status: 409,
      data: {
        status: 'divergence',
        divergences: [
          {
            ml_price_id: 'PXQ1',
            reason: 'amount_mismatch',
            live: { quantity: 5, amount: 150 },
            desired: { quantity: 5, amount: 100 },
          },
        ],
      },
    });

    expect(Array.isArray(data.detail.divergences)).toBe(true);
    expect(data.detail.divergences[0].live).toEqual({ quantity: 5, amount: 150 });
    expect(data.detail.divergences[0].desired).toEqual({ quantity: 5, amount: 100 });
  });

  // The trap inside the trap. `_error_detail_from_outcome` keeps EVERY key of
  // the write-service outcome except `synced`, and seven of those outcomes
  // carry their own `detail` string ("Writes are disabled (PXQ_WRITE_ENABLED=
  // false)", the raw proxy body, …). So the root body is
  // `{status, detail: "<string>"}` — a payload that already has a `detail`,
  // and a `detail` that is not the typed payload. Reading it as the answer
  // leaves `detail.status` undefined for every one of those seven statuses.
  it('lifts the typed root even when the payload carries its own detail string', async () => {
    const data = await throughInterceptor({
      status: 503,
      data: { status: 'disabled', detail: 'Writes are disabled (PXQ_WRITE_ENABLED=false)' },
    });

    expect(data.detail.status).toBe('disabled');
    // …and the backend's own note is kept as the field it always was.
    expect(data.detail.detail).toBe('Writes are disabled (PXQ_WRITE_ENABLED=false)');
  });

  // Every status in `_SYNC_STATUS_TO_HTTP` reaches the panel through the same
  // channel; two of them share an HTTP code with another, so `status` is the
  // only thing that can tell them apart.
  it.each([
    ['disabled', 503],
    ['rejected_not_eligible', 422],
    ['rejected_eligibility_unknown', 503],
    ['rejected_read_unavailable', 503],
    ['submitted_unconfirmed', 502],
    ['ambiguous_needs_reconcile', 502],
    ['rejected_by_proxy', 422],
  ])('keeps the sync status "%s" readable as a field', async (backendStatus, httpStatus) => {
    const data = await throughInterceptor({
      status: httpStatus,
      data: { status: backendStatus, detail: 'human-readable note from the write service' },
    });

    expect(data.detail.status).toBe(backendStatus);
  });

  // --- the React #31 protection this interceptor exists for -----------------

  // The original reason for the flattening: FastAPI/Pydantic body validation
  // returns `detail` as an ARRAY of objects, and components that render it
  // directly (`<div>{error}</div>`) throw React #31 on an object child.
  it('still joins a Pydantic 422 detail array into one renderable string', async () => {
    const data = await throughInterceptor({
      status: 422,
      data: {
        detail: [
          { loc: ['body', 'cantidad_minima'], msg: 'ensure this value is greater than 1', type: 'value_error' },
          { loc: ['body', 'precio_unitario'], msg: 'field required', type: 'value_error.missing' },
        ],
      },
    });

    expect(typeof data.detail).toBe('string');
    expect(data.detail).toBe('ensure this value is greater than 1; field required');
  });

  // A 422 array is the shape that actually caused React #31, so its guarantee
  // is asserted as the property itself, not just as a string equality.
  it('never leaves an object child in a Pydantic 422 detail', async () => {
    const data = await throughInterceptor({
      status: 422,
      data: { detail: [{ loc: ['body', 'x'], msg: 'field required', type: 'missing' }] },
    });

    expect(typeof data.detail).not.toBe('object');
  });

  // An untyped dict `detail` keeps today's behaviour exactly. More than a
  // hundred components do `<div>{data.detail || 'fallback'}</div>`, so the
  // passthrough must stay confined to payloads that carry a `status` string.
  it.each([
    [{ code: 'NOT_FOUND', message: 'Producto no encontrado' }, 'Producto no encontrado'],
    [{ msg: 'campo inválido' }, 'campo inválido'],
    [{ codigo: 'OP_CAJA_MONEDA', mensaje: 'La caja no coincide' }, 'La caja no coincide'],
  ])('still flattens the untyped dict %j to a string', async (detail, expected) => {
    const data = await throughInterceptor({ status: 409, data: { detail } });

    expect(data.detail).toBe(expected);
  });

  it('still stringifies a dict with no message-ish field rather than leaking an object', async () => {
    const data = await throughInterceptor({
      status: 409,
      data: { detail: { motivo: 'serial_ajeno', item_id_real: 42 } },
    });

    expect(typeof data.detail).toBe('string');
    expect(data.detail).toBe('{"motivo":"serial_ajeno","item_id_real":42}');
  });

  it('leaves a plain string detail alone', async () => {
    const data = await throughInterceptor({
      status: 403,
      data: { detail: 'No tienes permiso: pxq.escribir' },
    });

    expect(data.detail).toBe('No tienes permiso: pxq.escribir');
  });

  // --- the lift stays narrow ------------------------------------------------

  // The standard error envelope (`core/exceptions.py`, string details and any
  // dict carrying `code`) is NOT a typed application error. Inventing a
  // `detail` for it would change what a hundred-odd unrelated components
  // display, which is a separate change from this one.
  it('invents no detail for the standard {error: {code, message}} envelope', async () => {
    const data = await throughInterceptor({
      status: 403,
      data: { error: { code: 'INSUFFICIENT_PERMISSIONS', message: 'No tienes permiso: pxq.ver' } },
    });

    expect(data.detail).toBeUndefined();
  });

  it.each([
    ['a root dict with no status at all', { codigo: 'X', mensaje: 'Y' }],
    ['a root dict whose status is not a string', { status: 409, mensaje: 'Y' }],
  ])('invents no detail for %s', async (_label, body) => {
    const data = await throughInterceptor({ status: 409, data: body });

    expect(data.detail).toBeUndefined();
  });

  it('does nothing at all when the body is not an object (HTML error page)', async () => {
    const data = await throughInterceptor({ status: 502, data: '<html>502 Bad Gateway</html>' });

    expect(data).toBe('<html>502 Bad Gateway</html>');
  });
});
