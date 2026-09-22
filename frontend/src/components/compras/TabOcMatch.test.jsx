import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import TabOcMatch from './TabOcMatch';
import AdministracionCompras from '../../pages/AdministracionCompras';

const REFRESH_LABEL = 'También actualizar Factura/s y Pedido/s';

const ERROR_JOB = {
  id: 7,
  pedido_id: 44,
  pedido_numero: 'OC-44',
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
      ean: '7791234567890',
      ean_extract: '7790000000000',
      descripcion: 'Notebook 14',
      cantidad: '2.0000',
      precio_unitario: '12.3456',
      moneda: 'USD',
      match_estado: 'ok',
      confianza: 'media',
      motivo: 'color ambiguo',
      item_id: null,
    },
    {
      id: 2,
      indice: 2,
      ean: null,
      ean_extract: '7791111111111',
      descripcion: 'Mouse USB',
      cantidad: '0.5000',
      precio_unitario: '12.3456',
      moneda: 'USD',
      match_estado: 'ok',
      confianza: 'baja',
      motivo: null,
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

const LONG_ERROR =
  'linea 1 de error\nlinea 2 de error\nlinea 3 de error\nlinea 4 que no deberia verse completa';

const RUNNING_JOB = {
  ...ERROR_JOB,
  id: 9,
  pedido_id: 202,
  pedido_numero: 'OC-100',
  attachment_id: 91,
  status: 'running',
  progress_phase: 'matching',
  error_message: LONG_ERROR,
  retryable: false,
  excel_rel_path: null,
  acta: null,
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
  hookValue.retry.mockReset();
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
    expect(screen.queryByRole('checkbox', { name: REFRESH_LABEL })).toBeNull();
  });

  it('shows retry when the user can gestionar and the job is retryable', () => {
    mockTienePermiso.mockImplementation(
      (p) =>
        p === 'administracion.ver_ordenes_compra' ||
        p === 'administracion.gestionar_ordenes_compra',
    );
    render(<TabOcMatch />);
    expect(screen.getByRole('button', { name: /Reintentar/i })).toBeInTheDocument();
    const checkbox = screen.getByRole('checkbox', { name: REFRESH_LABEL });
    expect(checkbox).toBeInTheDocument();
    expect(checkbox).not.toBeChecked();
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
    expect(screen.queryByRole('checkbox', { name: REFRESH_LABEL })).toBeNull();
  });

  it('unchecked retry sends refrescar_doc_refs false', async () => {
    const user = userEvent.setup();
    mockTienePermiso.mockImplementation(
      (p) =>
        p === 'administracion.ver_ordenes_compra' ||
        p === 'administracion.gestionar_ordenes_compra',
    );
    render(<TabOcMatch />);
    await user.click(screen.getByRole('button', { name: /Reintentar/i }));
    expect(hookValue.retry).toHaveBeenCalledWith(ERROR_JOB.id, { refrescar_doc_refs: false });
  });

  it('checked retry sends refrescar_doc_refs true', async () => {
    const user = userEvent.setup();
    mockTienePermiso.mockImplementation(
      (p) =>
        p === 'administracion.ver_ordenes_compra' ||
        p === 'administracion.gestionar_ordenes_compra',
    );
    render(<TabOcMatch />);
    await user.click(screen.getByRole('checkbox', { name: REFRESH_LABEL }));
    await user.click(screen.getByRole('button', { name: /Reintentar/i }));
    expect(hookValue.retry).toHaveBeenCalledWith(ERROR_JOB.id, { refrescar_doc_refs: true });
  });
});

describe('TabOcMatch ops UX', () => {
  beforeEach(() => {
    mockTienePermiso.mockImplementation((p) => p === 'administracion.ver_ordenes_compra');
  });

  it('shows pedido numero OC-100 as the pedido identity', () => {
    resetHook({
      jobs: [RUNNING_JOB],
      total: 1,
      selected: RUNNING_JOB,
      selectedId: RUNNING_JOB.id,
    });
    render(<TabOcMatch />);
    expect(screen.getAllByText('OC-100').length).toBeGreaterThan(0);
    expect(screen.queryByText('202')).toBeNull();
  });

  it('shows Procesando badge plus matching phase subtitle', () => {
    resetHook({
      jobs: [RUNNING_JOB],
      total: 1,
      selected: RUNNING_JOB,
      selectedId: RUNNING_JOB.id,
    });
    render(<TabOcMatch />);
    expect(screen.getAllByText('Procesando').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Matcheando').length).toBeGreaterThan(0);
  });

  it('expands detail below the list, not as aside or modal', () => {
    resetHook({
      jobs: [RUNNING_JOB],
      total: 1,
      selected: RUNNING_JOB,
      selectedId: RUNNING_JOB.id,
    });
    const { container } = render(<TabOcMatch />);
    expect(container.querySelector('aside')).toBeNull();
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(screen.getByRole('heading', { name: /Job #9/ })).toBeInTheDocument();
    expect(screen.getByText('Notebook 14')).toBeInTheDocument();
  });

  it('keeps the full error text in title', () => {
    resetHook({
      jobs: [RUNNING_JOB],
      total: 1,
      selected: RUNNING_JOB,
      selectedId: RUNNING_JOB.id,
    });
    const { container } = render(<TabOcMatch />);
    const titled = container.querySelector('[title*="linea 4 que no deberia verse completa"]');
    expect(titled).not.toBeNull();
    expect(titled.getAttribute('title')).toBe(LONG_ERROR);
    expect(screen.getAllByText(/linea 4 que no deberia verse completa/).length).toBeGreaterThan(1);
  });
});

describe('TabOcMatch renglones EAN', () => {
  beforeEach(() => {
    mockTienePermiso.mockImplementation((p) => p === 'administracion.ver_ordenes_compra');
    resetHook({
      jobs: [ERROR_JOB],
      total: 1,
      selected: ERROR_JOB,
      selectedId: ERROR_JOB.id,
    });
  });

  it('locks renglones headers, EAN, unidades qty and 4dp precio', () => {
    const { container } = render(<TabOcMatch />);
    const tables = container.querySelectorAll('table');
    const renglonesTable = tables[1];
    const headers = [...renglonesTable.querySelectorAll('th')].map((th) => th.textContent);
    expect(headers).toEqual([
      '#',
      'EAN',
      'Descripción',
      'Cantidad',
      'P Unit',
      'Moneda',
      'Match',
      'Confianza',
      'Item',
    ]);
    expect(headers).not.toContain('ean_extract');

    const rows = renglonesTable.querySelectorAll('tbody tr');
    const firstCells = [...rows[0].querySelectorAll('td')].map((td) => td.textContent);
    const secondCells = [...rows[1].querySelectorAll('td')].map((td) => td.textContent);

    expect(firstCells[1]).toBe('7791234567890');
    expect(secondCells[1]).toBe('—');
    expect(firstCells[3]).toBe('2');
    expect(firstCells[3]).not.toContain('.0000');
    expect(secondCells[3]).toBe('0,5');
    expect(secondCells[3]).not.toBe('1');
    expect(firstCells[4]).toBe('12,3456');
    expect(screen.getByText(/Acta de matching/)).toBeInTheDocument();
    expect(container.querySelector('pre').textContent).toBe('Acta de matching\n- pack sin match');
  });

  it('does not add an ean_extract column header', () => {
    render(<TabOcMatch />);
    expect(screen.queryByRole('columnheader', { name: /ean_extract/i })).toBeNull();
  });
});
