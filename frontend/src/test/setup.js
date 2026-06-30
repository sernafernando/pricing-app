/**
 * Vitest global setup file.
 *
 * Verified facts (T1.1 — 2026-06-29):
 *   - Package manager: pnpm@10.33.0
 *   - services/api.js exports:
 *       default  — axios instance (has .get .post .patch .put .delete interceptors)
 *       productosAPI — { listar, listarTienda, stats, statsDinamicos, marcas, subcategorias,
 *                         categorias, obtenerMarcasPorPMs, obtenerSubcategoriasPorPMs }
 *   - Productos.jsx uses: productosAPI.listar (NOT listarTienda), productosAPI.statsDinamicos,
 *     productosAPI.marcas, productosAPI.subcategorias, productosAPI.obtenerMarcasPorPMs,
 *     productosAPI.obtenerSubcategoriasPorPMs
 *   - api (default) used for: /offsets-ganancia, /tipo-cambio-hoy, /auditoria/usuarios,
 *     /auditoria/tipos-accion, /usuarios/pms, /productos/* mutations, etc.
 *
 * Verified facts (T1.2 — 2026-06-29):
 *   - Keyboard nav activation key: Enter (when modoNavegacion===false && productos.length > 0)
 *   - Trigger names: iniciarEdicion, iniciarEdicionCuota, guardarPrecio, guardarCuota,
 *     toggleRebateRapido, toggleWebTransfRapido, toggleOutOfCardsRapido,
 *     toggleSeleccion, seleccionarTodos, pintarLote
 *   - Heavy import-time deps (leaflet/pdfme): NONE in Productos.jsx import chain.
 *     Leaflet is only in MapaEnviosFlex.jsx; pdfme only in DocumentDesigner lazy chunk.
 */

import '@testing-library/jest-dom';
import { vi, beforeEach, afterEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mock: services/api.js
// Default export = axios instance stub; productosAPI = named export stub
// ---------------------------------------------------------------------------
vi.mock('../services/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
  productosAPI: {
    listar: vi.fn().mockResolvedValue({ data: { productos: [], total: 0 } }),
    listarTienda: vi.fn().mockResolvedValue({ data: { productos: [], total: 0 } }),
    stats: vi.fn().mockResolvedValue({ data: {} }),
    statsDinamicos: vi.fn().mockResolvedValue({ data: {} }),
    marcas: vi.fn().mockResolvedValue({ data: { marcas: [] } }),
    subcategorias: vi.fn().mockResolvedValue({ data: { categorias: [] } }),
    categorias: vi.fn().mockResolvedValue({ data: [] }),
    obtenerMarcasPorPMs: vi.fn().mockResolvedValue({ data: { marcas: [] } }),
    obtenerSubcategoriasPorPMs: vi.fn().mockResolvedValue({ data: { subcategorias: [] } }),
  },
  authAPI: {
    login: vi.fn(),
    me: vi.fn(),
  },
  registerAuthFailureHandler: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Mock: authStore — stub that returns a fake user without reading localStorage
// at module init time (jsdom localStorage may not be available when authStore
// module is first imported). This avoids "localStorage.getItem is not a function".
// ---------------------------------------------------------------------------
vi.mock('../store/authStore', () => ({
  useAuthStore: (selector) => {
    const state = {
      user: { id: 1, nombre: 'Test User', roles: ['admin'] },
      token: 'test-token',
      isAuthenticated: true,
      logout: vi.fn(),
      setUser: vi.fn(),
      setToken: vi.fn(),
    };
    if (typeof selector === 'function') return selector(state);
    return state;
  },
}));

// ---------------------------------------------------------------------------
// Mock: PermisosContext — stub that grants ALL permissions (tienePermiso always true)
// Productos.jsx calls usePermisos() from this module; we intercept at the module
// level so the real PermisosProvider (which makes API calls) is never mounted.
// ---------------------------------------------------------------------------
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: () => true,
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

// ---------------------------------------------------------------------------
// Mock: lucide-react — use importOriginal to get all real exports
// (SVG icons render fine in jsdom; we just want the exports to resolve)
// ---------------------------------------------------------------------------
vi.mock('lucide-react', async (importOriginal) => {
  return await importOriginal();
});

// ---------------------------------------------------------------------------
// Stub localStorage (the jsdom environment may initialize without localStorage
// when --localstorage-file is provided without a path; stub it unconditionally)
// ---------------------------------------------------------------------------
const localStorageData = {};
const localStorageStub = {
  getItem: (key) => localStorageData[key] ?? null,
  setItem: (key, value) => { localStorageData[key] = String(value); },
  removeItem: (key) => { delete localStorageData[key]; },
  clear: () => { Object.keys(localStorageData).forEach(k => delete localStorageData[k]); },
  get length() { return Object.keys(localStorageData).length; },
  key: (i) => Object.keys(localStorageData)[i] ?? null,
};

Object.defineProperty(globalThis, 'localStorage', {
  writable: true,
  configurable: true,
  value: localStorageStub,
});

// ---------------------------------------------------------------------------
// Stub Element.prototype.scrollIntoView (jsdom doesn't implement it).
// The keyboard nav scroll-follow effect calls filaActiva.scrollIntoView(...)
// when a row becomes active. Without this stub, jsdom throws TypeError and
// crashes the keyboard-nav tests (CS-6a, CS-6b).
// ---------------------------------------------------------------------------
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}

// ---------------------------------------------------------------------------
// Stub window.matchMedia (jsdom doesn't implement it — ThemeContext needs it)
// ---------------------------------------------------------------------------
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// ---------------------------------------------------------------------------
// Suppress only known-safe, non-informative console.error patterns.
//
// INTENTIONALLY NARROW: act() and "not wrapped in act" warnings are NOT
// suppressed here. During hook extraction, those warnings are signal —
// they indicate async state updates happening outside React's control and
// should be visible so we can fix them.
//
// Only suppress messages that are permanently irrelevant to this codebase
// (e.g. ReactDOM.render deprecation from testing-library internals that
//  we cannot control and that carry zero signal for hook refactors).
// ---------------------------------------------------------------------------
const KNOWN_SAFE_SUPPRESSION_PATTERNS = [
  'Warning: ReactDOM.render is deprecated',
];

const originalError = console.error;
beforeEach(() => {
  console.error = (...args) => {
    const msg = typeof args[0] === 'string' ? args[0] : '';
    if (KNOWN_SAFE_SUPPRESSION_PATTERNS.some((p) => msg.includes(p))) return;
    originalError.call(console, ...args);
  };
});
afterEach(() => {
  console.error = originalError;
  vi.clearAllMocks();
});
