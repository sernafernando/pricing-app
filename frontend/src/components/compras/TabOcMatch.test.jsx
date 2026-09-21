import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TabOcMatch from './TabOcMatch';
import AdministracionCompras from '../../pages/AdministracionCompras';

const ERROR_JOB = {
  id: 7,
  pedido_id: 44,
  attachment_id: 90,
  status: 'error',
  error_message: 'USD sin tipo de cambio',
  acta: 'Acta de matching\n- pack sin match',
  excel_rel_path: null,
  retryable: true,
  created_at: '2026-09-19T10:00:00Z',
  renglones: [
    {
      id: 1,
      indice: 1,
      descripcion: 'Notebook 14',
      cantidad: '2',
      precio_unitario: '100',
      moneda: 'USD',
      match_estado: 'ok',
      confianza: 'media',
      motivo: 'color ambiguo',
      item_id: null,
    },
  ],
};

const DONE_JOB = {
  ...ERROR_JOB,
  id: 8,
  status: 'done',
  error_message: null,
  retryable: false,
  excel_rel_path: '8/carga.xlsx',
};

const { hookValue, mockTienePermiso } = vi.hoisted(() => ({
  hookValue: {
    jobs: [],
    total: 0,
    selected: null,
    selectedId: null,
    setSelectedId: vi.fn(),
    loading: false,
    error: null,
    refresh: vi.fn(),
    retry: vi.fn(),
    downloadExcel: vi.fn(),
  },
  mockTienePermiso: vi.fn(() => true),
}));

vi.mock('../../hooks/useOcMatch', () => ({ default: () => hookValue }));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: mockTienePermiso,
    cargandoPermisos: false,
  }),
}));

function resetHook(overrides = {}) {
  hookValue.jobs = [];
  hookValue.total = 0;
  hookValue.selected = null;
  hookValue.selectedId = null;
  hookValue.loading = false;
  hookValue.error = null;
  Object.assign(hookValue, overrides);
}

describe('TABS oc-match visibility', () => {
  it('does not render the OC Match tab without view permiso', () => {
    mockTienePermiso.mockImplementation(() => false);
    render(
      <MemoryRouter>
        <AdministracionCompras />
      </MemoryRouter>,
    );
    expect(screen.queryByRole('tab', { name: /OC Match/i })).toBeNull();
  });

  it('renders the OC Match tab when the user has view permiso', () => {
    mockTienePermiso.mockImplementation((p) => p === 'administracion.ver_ordenes_compra');
    render(
      <MemoryRouter>
        <AdministracionCompras />
      </MemoryRouter>,
    );
    expect(screen.getByRole('tab', { name: /OC Match/i })).toBeInTheDocument();
  });
});

describe('TabOcMatch retry gate', () => {
  beforeEach(() => {
    mockTienePermiso.mockImplementation((p) => p === 'administracion.ver_ordenes_compra');
    resetHook({
      jobs: [ERROR_JOB],
      total: 1,
      selected: ERROR_JOB,
      selectedId: ERROR_JOB.id,
    });
  });

  it('hides retry for a view-only user on a retryable error job', () => {
    render(<TabOcMatch />);
    expect(screen.getByText(/Acta de matching/)).toBeInTheDocument();
    expect(screen.getByText('Notebook 14')).toBeInTheDocument();
    expect(screen.getAllByText('USD sin tipo de cambio').length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /Reintentar/i })).toBeNull();
  });

  it('shows retry when the user can gestionar and the job is retryable', () => {
    mockTienePermiso.mockImplementation(
      (p) =>
        p === 'administracion.ver_ordenes_compra' ||
        p === 'administracion.gestionar_ordenes_compra',
    );
    render(<TabOcMatch />);
    expect(screen.getByRole('button', { name: /Reintentar/i })).toBeInTheDocument();
  });

  it('shows renglones, acta and excel download on a done job', () => {
    resetHook({
      jobs: [DONE_JOB],
      total: 1,
      selected: DONE_JOB,
      selectedId: DONE_JOB.id,
    });
    render(<TabOcMatch />);
    expect(screen.getByText('Notebook 14')).toBeInTheDocument();
    expect(screen.getByText(/Acta de matching/)).toBeInTheDocument();
    expect(screen.getByText('media')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Descargar Excel/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Reintentar/i })).toBeNull();
  });
});
