import { describe, it, expect, vi, beforeEach } from 'vitest';

// setup.js mockea globalmente '../services/api' con stubs vi.fn() (lo necesitan
// los tests de página). Esta suite ejercita la implementación REAL del
// interceptor de respuesta, así que desmockea el módulo y mockea axios —
// mismo arnés que `api.pxq.test.js`.
vi.unmock('../services/api');

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockUse = vi.fn();
// Capturados, no stubbeados: el interceptor de respuesta ES la unidad bajo
// prueba, así que el mock tiene que devolverlo en vez de tragárselo como hace
// `mockUse` del lado del request.
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
 * El envelope estándar de error del backend, visto desde el frontend.
 *
 * `backend/app/core/exceptions.py` (`http_exception_handler`) emite tres
 * formas de body y NINGUNA tiene clave `detail`:
 *   1. `detail` dict CON `code`  → `{error: {code, message}}`
 *   2. `detail` dict SIN `code`  → el dict crudo COMO RAÍZ del body
 *   3. `detail` string           → `{error: {code, message}}`, code por status
 *
 * O sea que para la forma 1 y la 3 — el envelope estándar, el camino que toma
 * la enorme mayoría de los errores de la API — `data.detail` llegaba
 * `undefined`. Los 287 `data.detail || 'fallback'` repartidos en 106 archivos
 * mostraban SIEMPRE el fallback genérico y el mensaje real del backend no
 * llegaba a la pantalla.
 */
describe('response interceptor — standard {error: {code, message}} envelope', () => {
  beforeEach(() => {
    vi.resetModules();
    responseInterceptors.length = 0;
    mockGet.mockReset();
    mockPost.mockReset();
  });

  /**
   * Empuja `response` por el interceptor REAL registrado y devuelve la `data`
   * que un componente terminaría leyendo. También asserta que el interceptor
   * sigue rechazando con el mismo objeto error — normalizar un payload nunca
   * puede convertir una falla en un éxito.
   */
  async function throughInterceptor(response) {
    await import('./api');
    const { onRejected } = responseInterceptors[responseInterceptors.length - 1];
    const error = { config: { url: '/productos/42' }, response };
    await expect(onRejected(error)).rejects.toBe(error);
    return error.response.data;
  }

  // --- el desenvuelto ------------------------------------------------------

  it('shows the backend message instead of the generic fallback', async () => {
    const data = await throughInterceptor({
      status: 404,
      data: { error: { code: 'NOT_FOUND', message: 'Producto no encontrado' } },
    });

    expect(data.detail).toBe('Producto no encontrado');
  });

  // La invariante que justifica el interceptor entero. Los 287 call sites
  // hacen `<div>{data.detail || 'fallback'}</div>`: un objeto ahí es un hijo
  // no renderizable y React tira el error #31. El desenvuelto produce un
  // STRING, nunca un objeto, y esta assertion es lo que lo mantiene así.
  it('never leaves an object where a component renders a text child', async () => {
    const data = await throughInterceptor({
      status: 404,
      data: { error: { code: 'NOT_FOUND', message: 'Producto no encontrado' } },
    });

    expect(typeof data.detail).toBe('string');
  });

  // El envelope es el mismo para toda la API; el status HTTP solo cambia el
  // `code` que deriva `_status_to_code`, no la forma del body.
  it.each([
    [401, 'INVALID_TOKEN', 'Token expirado'],
    [403, 'INSUFFICIENT_PERMISSIONS', 'No tienes permiso: productos.editar'],
    [500, 'INTERNAL_ERROR', 'Error interno del servidor'],
  ])('unwraps the envelope on a %i the same way', async (status, code, message) => {
    const data = await throughInterceptor({ status, data: { error: { code, message } } });

    expect(data.detail).toBe(message);
  });

  // 18 archivos ya se comieron este bug y lo esquivaron a mano leyendo
  // `err.response?.data?.error?.message || ... || 'fallback'` — `authStore.js`
  // entre ellos. El desenvuelto AGREGA `detail`, no reemplaza ni muta `error`,
  // así que esos 18 siguen funcionando exactamente igual.
  it('keeps data.error readable for the files that already work around this', async () => {
    const data = await throughInterceptor({
      status: 401,
      data: { error: { code: 'INVALID_TOKEN', message: 'Token expirado' } },
    });

    expect(data.error.message).toBe('Token expirado');
    expect(data.error.code).toBe('INVALID_TOKEN');
    expect(data.detail).toBe('Token expirado');
  });

  // --- lo que el desenvuelto NO pisa ---------------------------------------

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

  // Un error de aplicación TIPADO se lee por campos, no se renderiza. Si un
  // payload es a la vez raíz tipada y trae `error`, gana lo tipado: aplanarlo
  // a string dejaría `detail.status` en `undefined` y mataría las ramas que
  // dependen de él (`adopt_conflict`, `divergence`).
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

  // --- el predicado se mantiene angosto ------------------------------------

  // `error` como string suelto no es el envelope estándar. Desenvolverlo a
  // ciegas con `data.error.message` sería `undefined`, y peor: asumir que
  // cualquier clave `error` es el envelope invita a que entre un objeto.
  it('ignores a payload whose error is plain text', async () => {
    const data = await throughInterceptor({ status: 500, data: { error: 'texto plano' } });

    expect(data.detail).toBeUndefined();
  });

  it('ignores an envelope with no message to show', async () => {
    const data = await throughInterceptor({ status: 500, data: { error: { code: 'X' } } });

    expect(data.detail).toBeUndefined();
  });

  // Sin este chequeo, un `message` numérico entraría como número a un lugar
  // donde el contrato con los componentes es "string o nada".
  it('ignores an envelope whose message is not a string', async () => {
    const data = await throughInterceptor({ status: 500, data: { error: { message: 123 } } });

    expect(data.detail).toBeUndefined();
  });

  // --- regresiones del comportamiento previo -------------------------------

  // La razón original de existir del interceptor: la validación de body de
  // FastAPI/Pydantic devuelve `detail` como ARRAY de objetos.
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

  // --- hueco conocido, deliberadamente NO cerrado acá ----------------------

  // La forma 2 del handler: un dict de `detail` SIN `code` vuelve como RAÍZ
  // del body. Si además no tiene `status`, no es el envelope estándar ni un
  // error tipado, así que `detail` sigue `undefined` y el componente muestra
  // su fallback. Es exactamente lo que emite `backend/app/routers/prearmado.py`
  // con `{message, errores}`.
  //
  // Este cambio NO lo arregla, y es a propósito: cerrarlo pide poner el dict
  // — un OBJETO — en `detail`, que es precisamente el React #31 que este
  // interceptor existe para evitar. Cerrarlo de verdad exige elegir qué campo
  // es el texto para cada forma cruda, y eso es otro cambio.
  it('leaves the known gap open: a raw root dict with neither code nor status', async () => {
    const data = await throughInterceptor({
      status: 422,
      data: { message: 'x', errores: ['a'] },
    });

    expect(data.detail).toBeUndefined();
  });
});
