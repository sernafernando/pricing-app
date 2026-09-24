import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import TabOcMatch from './TabOcMatch';
import AdministracionCompras from '../../pages/AdministracionCompras';

const REFRESH_LABEL = 'También actualizar Factura/s y Pedido/s';
const DEDICATED_REFRESH = 'Actualizar Factura/s y Pedido/s';
const REFRESH_TITLE = 'Relee el PDF. Puede restaurar números borrados a mano.';
const REFRESH_HELPER =
  'Vuelve a leer el PDF y puede restaurar números de factura o pedido que se hayan borrado a mano.';

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
      ean_ultimos4: '0000',
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
      ean_ultimos4: null,
      descripcion: 'Mouse USB',
      cantidad: '0.5000',
      precio_unitario: '12.3456',
      moneda: 'USD',
      match_estado: 'ok',
      confianza: 'baja',
      motivo: null,
      item_id: null,
    },
    {
      id: 3,
      indice: 3,
      ean: null,
      ean_extract: null,
      ean_ultimos4: '9862',
      descripcion: 'Cable HDMI',
      cantidad: '1',
      precio_unitario: '1.0000',
      moneda: 'USD',
      match_estado: 'no_hallado',
      confianza: 'baja',
      motivo: null,
      item_id: null,
    },
    {
      id: 4,
      indice: 4,
      ean: null,
      ean_extract: null,
      ean_ultimos4: null,
      descripcion: 'Sin codigo',
      cantidad: '1',
      precio_unitario: '1.0000',
      moneda: 'USD',
      match_estado: 'no_hallado',
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
    refreshDocRefs: vi.fn(),
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

function renglonesTable(container) {
  const tables = [...container.querySelectorAll('table')];
  return tables.find((table) =>
    [...table.querySelectorAll(':scope > thead th')].some((th) => th.textContent === 'EAN'),
  );
}

function resetHook(overrides = {}) {
  hookValue.jobs = [];
  hookValue.total = 0;
  hookValue.selected = null;
  hookValue.selectedId = null;
  hookValue.loading = false;
  hookValue.error = null;
  hookValue.retry.mockReset();
  hookValue.refreshDocRefs.mockReset();
  hookValue.setSelectedId.mockReset();
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

  it('expands detail under the selected row, not as aside or modal', () => {
    resetHook({
      jobs: [RUNNING_JOB],
      total: 1,
      selected: RUNNING_JOB,
      selectedId: RUNNING_JOB.id,
    });
    const { container } = render(<TabOcMatch />);
    expect(container.querySelector('aside')).toBeNull();
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    const heading = screen.getByRole('heading', { name: /Job #9/ });
    expect(heading).toBeInTheDocument();
    expect(screen.getByText('Notebook 14')).toBeInTheDocument();
    const listTable = container.querySelectorAll('table')[0];
    expect(listTable.contains(heading)).toBe(true);
    const listRows = listTable.querySelectorAll(':scope > tbody > tr');
    expect(listRows).toHaveLength(2);
    expect(listRows[1].contains(heading)).toBe(true);
  });

  it('same-row click toggles collapse', async () => {
    const user = userEvent.setup();
    resetHook({
      jobs: [DONE_JOB],
      total: 1,
      selected: DONE_JOB,
      selectedId: DONE_JOB.id,
    });
    render(<TabOcMatch />);
    expect(screen.getByRole('heading', { name: /Job #8/ })).toBeInTheDocument();
    await user.click(screen.getByText('#8'));
    expect(hookValue.setSelectedId).toHaveBeenCalledWith(null);
  });

  it('other row moves the expand', async () => {
    const user = userEvent.setup();
    resetHook({
      jobs: [DONE_JOB, ERROR_JOB],
      total: 2,
      selected: DONE_JOB,
      selectedId: DONE_JOB.id,
    });
    render(<TabOcMatch />);
    await user.click(screen.getByText('#7'));
    expect(hookValue.setSelectedId).toHaveBeenCalledWith(ERROR_JOB.id);
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

describe('TabOcMatch dedicated doc-refs refresh', () => {
  const gestionar = (p) =>
    p === 'administracion.ver_ordenes_compra' ||
    p === 'administracion.gestionar_ordenes_compra';

  it('shows dedicated button for done plus gestionar', () => {
    mockTienePermiso.mockImplementation(gestionar);
    resetHook({
      jobs: [DONE_JOB],
      total: 1,
      selected: DONE_JOB,
      selectedId: DONE_JOB.id,
    });
    render(<TabOcMatch />);
    const button = screen.getByRole('button', { name: DEDICATED_REFRESH });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute('title', REFRESH_TITLE);
    expect(screen.getByText(REFRESH_HELPER)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Reintentar/i })).toBeNull();
    expect(screen.queryByText(/doc_refs_aplicado_at/i)).toBeNull();
  });

  it('error keeps Retry plus checkbox and shows dedicated button', () => {
    mockTienePermiso.mockImplementation(gestionar);
    resetHook({
      jobs: [ERROR_JOB],
      total: 1,
      selected: ERROR_JOB,
      selectedId: ERROR_JOB.id,
    });
    render(<TabOcMatch />);
    const button = screen.getByRole('button', { name: DEDICATED_REFRESH });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute('title', REFRESH_TITLE);
    expect(screen.getByText(REFRESH_HELPER)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Reintentar/i })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: REFRESH_LABEL })).toBeInTheDocument();
  });

  it('hides dedicated button for view-only', () => {
    mockTienePermiso.mockImplementation((p) => p === 'administracion.ver_ordenes_compra');
    resetHook({
      jobs: [DONE_JOB],
      total: 1,
      selected: DONE_JOB,
      selectedId: DONE_JOB.id,
    });
    render(<TabOcMatch />);
    expect(screen.queryByRole('button', { name: DEDICATED_REFRESH })).toBeNull();
    expect(screen.queryByText(REFRESH_HELPER)).toBeNull();
  });

  it.each(['queued', 'running', 'skipped'])('hides dedicated button on %s', (status) => {
    mockTienePermiso.mockImplementation(gestionar);
    const job = { ...RUNNING_JOB, id: 11, status, retryable: false };
    resetHook({
      jobs: [job],
      total: 1,
      selected: job,
      selectedId: job.id,
    });
    render(<TabOcMatch />);
    expect(screen.queryByRole('button', { name: DEDICATED_REFRESH })).toBeNull();
  });

  it('click enqueues and shows non-blocking banner', async () => {
    const user = userEvent.setup();
    mockTienePermiso.mockImplementation(gestionar);
    resetHook({
      jobs: [DONE_JOB],
      total: 1,
      selected: DONE_JOB,
      selectedId: DONE_JOB.id,
    });
    hookValue.refreshDocRefs.mockResolvedValue({ ...DONE_JOB });
    render(<TabOcMatch />);
    await user.click(screen.getByRole('button', { name: DEDICATED_REFRESH }));
    expect(hookValue.refreshDocRefs).toHaveBeenCalledWith(DONE_JOB.id);
    expect(hookValue.retry).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('Actualización encolada');
    expect(screen.getByRole('button', { name: DEDICATED_REFRESH })).toBeDisabled();
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
    const table = renglonesTable(container);
    const headers = [...table.querySelectorAll(':scope > thead th')].map((th) => th.textContent);
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

    const rows = table.querySelectorAll(':scope > tbody > tr');
    const firstCells = [...rows[0].querySelectorAll(':scope > td')].map((td) => td.textContent);
    const secondCells = [...rows[1].querySelectorAll(':scope > td')].map((td) => td.textContent);

    expect(firstCells[1]).toBe('7791234567890');
    expect(secondCells[1]).toBe('7791111111111');
    expect(firstCells[3]).toBe('2');
    expect(firstCells[3]).not.toContain('.0000');
    expect(secondCells[3]).toBe('0,5');
    expect(secondCells[3]).not.toBe('1');
    expect(firstCells[4]).toBe('12,3456');
    expect(screen.getByText(/Acta de matching/)).toBeInTheDocument();
    expect(container.querySelector('pre').textContent).toBe('Acta de matching\n- pack sin match');
  });

  it('falls back to ean_extract then ultimos4 with secondary style', () => {
    const { container } = render(<TabOcMatch />);
    const table = renglonesTable(container);
    const rows = table.querySelectorAll(':scope > tbody > tr');
    const extractCell = rows[1].querySelectorAll(':scope > td')[1].querySelector('span');
    const last4Cell = rows[2].querySelectorAll(':scope > td')[1].querySelector('span');
    const emptyCell = rows[3].querySelectorAll(':scope > td')[1].querySelector('span');

    expect(extractCell.textContent).toBe('7791111111111');
    expect(extractCell.getAttribute('title')).toBe('EAN del documento, sin match en GBP');
    expect(extractCell.className).toMatch(/tdSecondary/);

    expect(last4Cell.textContent).toBe('…9862');
    expect(last4Cell.getAttribute('title')).toBe('Últimos 4 del documento, sin match en GBP');
    expect(last4Cell.className).toMatch(/tdSecondary/);

    expect(emptyCell.textContent).toBe('—');
    expect(emptyCell.getAttribute('title')).toBeNull();
    expect(container.querySelector('pre').textContent).toBe('Acta de matching\n- pack sin match');
  });

  it('does not add an ean_extract column header', () => {
    render(<TabOcMatch />);
    expect(screen.queryByRole('columnheader', { name: /ean_extract/i })).toBeNull();
  });
});
