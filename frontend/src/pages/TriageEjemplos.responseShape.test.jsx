/**
 * PR5b task-4 requirement: at least one test must assert against the REAL
 * backend response shape, mocked at the AXIOS layer with the actual JSON
 * keys (`EjemploResponse`: id, campo, texto, valor_ia, valor_corregido,
 * active, created_at — deliberately NO `embedding`), not at the service
 * layer. A mocked-at-service-layer test would happily pass even if a real
 * field the UI needs was never serialized by the backend (see PR4b
 * near-miss noted in the task).
 *
 * `ejemplosAPI` itself is the REAL implementation here — only the
 * underlying `axios` instance is replaced.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import TriageEjemplos from './TriageEjemplos';

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }));

vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: mockGet,
      patch: vi.fn(),
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    }),
  },
}));

// `src/test/setup.js` globally stubs `../services/api` (it predates
// `ejemplosAPI`). This file needs the REAL module — its `ejemplosAPI`
// functions must run for real against the mocked axios instance above —
// so override that global stub with the actual module.
vi.mock('../services/api', async () => vi.importActual('../services/api'));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: () => true, loading: false }),
  PermisosProvider: ({ children }) => children,
}));

beforeEach(() => {
  mockGet.mockReset();
});

describe('TriageEjemplos — real backend response shape (axios layer)', () => {
  it('renders a row from the exact JSON keys EjemploResponse serializes', async () => {
    mockGet.mockResolvedValue({
      data: [
        {
          id: 1,
          campo: 'severidad',
          texto: 'El sistema no permite facturar desde hace dos horas',
          valor_ia: 'mayor',
          valor_corregido: 'critica',
          active: true,
          created_at: '2026-08-10T12:00:00Z',
          // deliberately NO `embedding` — matches EjemploResponse exactly
        },
      ],
    });

    render(<TriageEjemplos />);

    expect(
      await screen.findByText('El sistema no permite facturar desde hace dos horas'),
    ).toBeInTheDocument();
    expect(screen.getByText('mayor')).toBeInTheDocument();
    expect(screen.getByText('critica')).toBeInTheDocument();
  });
});
