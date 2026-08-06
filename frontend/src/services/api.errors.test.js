import { describe, it, expect, vi, beforeEach } from 'vitest';

// setup.js globally mocks '../services/api' with plain vi.fn() stubs (needed
// by page-level tests). This suite exercises the REAL response interceptor,
// so it unmocks the module and mocks axios directly instead — same harness as
// `api.pxq.test.js`.
vi.unmock('../services/api');

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockUse = vi.fn();
// Captured, not stubbed: the response interceptor IS the unit under test, so
// the mock has to hand it back rather than swallow it like `mockUse` does for
// the request side.
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

/**
 * The backend's standard error envelope, seen from the frontend.
 *
 * `backend/app/core/exceptions.py` (`http_exception_handler`) emits three body
 * shapes and NONE of them carries a `detail` key:
 *   1. dict detail WITH `code`    → `{error: {code, message}}`
 *   2. dict detail WITHOUT `code` → the raw dict AS THE ROOT of the body
 *   3. string detail              → `{error: {code, message}}`, code by status
 *
 * So for shapes 1 and 3 — the standard envelope, the path the vast majority of
 * this API's errors take — `data.detail` arrived `undefined`. The 287
 * `data.detail || 'fallback'` call sites across 106 files ALWAYS showed the
 * generic fallback, and the real backend message never reached the screen.
 */
describe('response interceptor — standard {error: {code, message}} envelope', () => {
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
    const error = { config: { url: '/productos/42' }, response };
    await expect(onRejected(error)).rejects.toBe(error);
    return error.response.data;
  }

  // --- the unwrap ----------------------------------------------------------

  it('shows the backend message instead of the generic fallback', async () => {
    const data = await throughInterceptor({
      status: 404,
      data: { error: { code: 'NOT_FOUND', message: 'Producto no encontrado' } },
    });

    expect(data.detail).toBe('Producto no encontrado');
  });

  // The invariant that justifies the whole interceptor. The 287 call sites do
  // `<div>{data.detail || 'fallback'}</div>`: an object there is an
  // unrenderable child and React throws error #31. The unwrap yields a STRING,
  // never an object, and this assertion is what keeps it that way.
  it('never leaves an object where a component renders a text child', async () => {
    const data = await throughInterceptor({
      status: 404,
      data: { error: { code: 'NOT_FOUND', message: 'Producto no encontrado' } },
    });

    expect(typeof data.detail).toBe('string');
  });

  // The envelope is the same across the whole API; the HTTP status only
  // changes the `code` that `_status_to_code` derives, not the body shape.
  it.each([
    [401, 'INVALID_TOKEN', 'Token expirado'],
    [403, 'INSUFFICIENT_PERMISSIONS', 'No tienes permiso: productos.editar'],
    [500, 'INTERNAL_ERROR', 'Error interno del servidor'],
  ])('unwraps the envelope on a %i the same way', async (status, code, message) => {
    const data = await throughInterceptor({ status, data: { error: { code, message } } });

    expect(data.detail).toBe(message);
  });

  // 18 files already hit this bug and worked around it by hand, reading
  // `err.response?.data?.error?.message || ... || 'fallback'` — `authStore.js`
  // among them. The unwrap ADDS `detail`; it never replaces or mutates
  // `error`, so those 18 keep behaving exactly as before.
  it('keeps data.error readable for the files that already work around this', async () => {
    const data = await throughInterceptor({
      status: 401,
      data: { error: { code: 'INVALID_TOKEN', message: 'Token expirado' } },
    });

    expect(data.error.message).toBe('Token expirado');
    expect(data.error.code).toBe('INVALID_TOKEN');
    expect(data.detail).toBe('Token expirado');
  });

  // --- what the unwrap refuses to clobber ----------------------------------

  it('does not overwrite a detail the backend already sent', async () => {
    const data = await throughInterceptor({
      status: 403,
      data: {
        detail: 'No tienes permiso: pxq.escribir',
        error: { code: 'INSUFFICIENT_PERMISSIONS', message: 'otro mensaje' },
      },
    });

    expect(data.detail).toBe('No tienes permiso: pxq.escribir');
  });

  // A TYPED application error is read field by field, not rendered. When a
  // payload is both a typed root and carries `error`, the typed branch wins:
  // flattening it to a string would leave `detail.status` `undefined` and kill
  // the branches that depend on it (`adopt_conflict`, `divergence`).
  it('yields to the typed application error when the payload is both', async () => {
    const data = await throughInterceptor({
      status: 409,
      data: {
        status: 'adopt_conflict',
        conflicts: [{ tier_id: 3, cantidad_minima: 12 }],
        error: { code: 'ALREADY_EXISTS', message: 'x' },
      },
    });

    expect(typeof data.detail).toBe('object');
    expect(data.detail.status).toBe('adopt_conflict');
    expect(data.detail.conflicts).toEqual([{ tier_id: 3, cantidad_minima: 12 }]);
  });

  // --- the predicate stays narrow ------------------------------------------

  // A bare string under `error` is not the standard envelope. Unwrapping it
  // blindly would make `data.error.message` `undefined`, and worse: assuming
  // any `error` key is the envelope invites an object in.
  it('ignores a payload whose error is plain text', async () => {
    const data = await throughInterceptor({ status: 500, data: { error: 'texto plano' } });

    expect(data.detail).toBeUndefined();
  });

  it('ignores an envelope with no message to show', async () => {
    const data = await throughInterceptor({ status: 500, data: { error: { code: 'X' } } });

    expect(data.detail).toBeUndefined();
  });

  // Without this check a numeric `message` would land as a number in a place
  // whose contract with the components is "a string or nothing".
  it('ignores an envelope whose message is not a string', async () => {
    const data = await throughInterceptor({ status: 500, data: { error: { message: 123 } } });

    expect(data.detail).toBeUndefined();
  });

  // --- regressions of the previous behavior --------------------------------

  // The interceptor's original reason to exist: FastAPI/Pydantic body
  // validation returns `detail` as an ARRAY of objects.
  it('still joins a Pydantic 422 detail array into one renderable string', async () => {
    const data = await throughInterceptor({
      status: 422,
      data: { detail: [{ msg: 'a' }, { msg: 'b' }] },
    });

    expect(data.detail).toBe('a; b');
  });

  it('still lifts a typed root that carries no error key', async () => {
    const data = await throughInterceptor({
      status: 409,
      data: {
        status: 'divergence',
        divergences: [{ ml_price_id: 'PXQ1', reason: 'amount_mismatch' }],
      },
    });

    expect(data.detail.divergences).toEqual([{ ml_price_id: 'PXQ1', reason: 'amount_mismatch' }]);
  });

  // --- known gap, deliberately NOT closed here -----------------------------

  // Shape 2 of the handler: a dict detail WITHOUT `code` comes back as the
  // ROOT of the body. When it also has no `status` it is neither the standard
  // envelope nor a typed error, so `detail` stays `undefined` and the
  // component shows its fallback. That is exactly what
  // `backend/app/routers/prearmado.py` emits with `{message, errores}`.
  //
  // This change does NOT fix it, on purpose: closing it means putting the dict
  // — an OBJECT — into `detail`, which is precisely the React #31 this
  // interceptor exists to prevent. Closing it properly requires deciding which
  // field is the text for each raw shape, and that is a separate change.
  it('leaves the known gap open: a raw root dict with neither code nor status', async () => {
    const data = await throughInterceptor({
      status: 422,
      data: { message: 'x', errores: ['a'] },
    });

    expect(data.detail).toBeUndefined();
  });
});
