/**
 * Tests for the correction-curation panel (tickets-triage-feedback PR5b).
 *
 * Covers: permission-gated entry point, filter-by-campo refetch, in-place
 * toggle (no reload), empty states (no examples at all / none for this
 * campo), and a failed toggle surfacing an inline error without
 * optimistically flipping the row.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ejemplosAPI } from '../services/api';
import TriageEjemplos from './TriageEjemplos';

// Service-layer mock (this file's convention — matches Tickets.test.jsx /
// MLQuestions.test.jsx). A SEPARATE file,
// `TriageEjemplos.responseShape.test.jsx`, mocks at the axios layer instead
// with the literal backend JSON keys, per the PR5b task-4 requirement.
vi.mock('../services/api', () => ({
  ejemplosAPI: { listar: vi.fn(), toggle: vi.fn() },
}));

const api = ejemplosAPI;

const mockTienePermiso = vi.fn(() => true);
let mockLoading = false;

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    tienePermiso: (codigo) => mockTienePermiso(codigo),
    loading: mockLoading,
  }),
  PermisosProvider: ({ children }) => children,
}));

const EJEMPLO_SEVERIDAD = {
  id: 1,
  campo: 'severidad',
  texto: 'El sistema no permite facturar desde hace dos horas',
  valor_ia: 'mayor',
  valor_corregido: 'critica',
  active: true,
  created_at: '2026-08-10T12:00:00Z',
};

const EJEMPLO_URGENCIA = {
  id: 2,
  campo: 'urgencia',
  texto: 'Consulta sobre el color disponible de un producto',
  valor_ia: 'alta',
  valor_corregido: 'baja',
  active: false,
  created_at: '2026-08-11T09:30:00Z',
};

function mockListar(items) {
  api.listar.mockImplementation((campo) => {
    const filtered = campo ? items.filter((i) => i.campo === campo) : items;
    return Promise.resolve({ data: filtered });
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockTienePermiso.mockReturnValue(true);
  mockLoading = false;
});

describe('TriageEjemplos — entry-point permission gate', () => {
  it('renders "no permission" state when user lacks tickets.triage.ejemplos', () => {
    mockTienePermiso.mockReturnValue(false);
    mockListar([]);
    render(<TriageEjemplos />);
    expect(screen.getByText(/no ten[eé]s permisos/i)).toBeInTheDocument();
    expect(api.listar).not.toHaveBeenCalled();
  });
});

describe('TriageEjemplos — panel', () => {
  it('renders rows for the selected campo (severidad by default)', async () => {
    mockListar([EJEMPLO_SEVERIDAD, EJEMPLO_URGENCIA]);
    render(<TriageEjemplos />);

    await waitFor(() => expect(api.listar).toHaveBeenCalled());
    expect(await screen.findByText(EJEMPLO_SEVERIDAD.texto)).toBeInTheDocument();
    expect(screen.queryByText(EJEMPLO_URGENCIA.texto)).not.toBeInTheDocument();
  });

  it('switching the filter to urgencia refetches and shows only that campo', async () => {
    mockListar([EJEMPLO_SEVERIDAD, EJEMPLO_URGENCIA]);
    const user = userEvent.setup();
    render(<TriageEjemplos />);

    await screen.findByText(EJEMPLO_SEVERIDAD.texto);

    await user.click(screen.getByRole('button', { name: /urgencia/i }));

    await waitFor(() =>
      expect(api.listar).toHaveBeenLastCalledWith('urgencia', expect.objectContaining({ limit: 200 })),
    );
    expect(await screen.findByText(EJEMPLO_URGENCIA.texto)).toBeInTheDocument();
    expect(screen.queryByText(EJEMPLO_SEVERIDAD.texto)).not.toBeInTheDocument();
  });

  it('toggling a row off updates it in place without a full page reload, and drops the counter', async () => {
    mockListar([EJEMPLO_SEVERIDAD]);
    api.toggle.mockResolvedValue({ data: { ...EJEMPLO_SEVERIDAD, active: false } });
    const user = userEvent.setup();
    render(<TriageEjemplos />);

    await screen.findByText(EJEMPLO_SEVERIDAD.texto);
    expect(screen.getByText(/1 de 1 influyen/i)).toBeInTheDocument();

    const row = screen.getByText(EJEMPLO_SEVERIDAD.texto).closest('[data-testid="ejemplo-row"]');
    await user.click(within(row).getByRole('checkbox'));

    await waitFor(() => expect(api.toggle).toHaveBeenCalledWith(1, false));
    await waitFor(() => expect(screen.getByText(/0 de 1 influyen/i)).toBeInTheDocument());
    // no navigation/reload happened — component is still mounted with same DOM node
    expect(row).toBeInTheDocument();
  });

  it('renders the "no examples at all" empty state when the corpus is empty', async () => {
    mockListar([]);
    render(<TriageEjemplos />);
    expect(await screen.findByText(/todav[ií]a no hay ejemplos/i)).toBeInTheDocument();
  });

  it('renders the "none for this campo" empty state when only the other campo has examples', async () => {
    mockListar([EJEMPLO_URGENCIA]);
    const user = userEvent.setup();
    render(<TriageEjemplos />);

    await waitFor(() => expect(api.listar).toHaveBeenCalled());
    expect(await screen.findByText(/no hay ejemplos.*severidad|prob[aá] con.*urgencia/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /urgencia/i }));
    expect(await screen.findByText(EJEMPLO_URGENCIA.texto)).toBeInTheDocument();
  });

  it('a failed toggle surfaces an inline error and does not optimistically flip the row', async () => {
    mockListar([EJEMPLO_SEVERIDAD]);
    api.toggle.mockRejectedValue({ response: { data: { detail: 'Error de red' } } });
    const user = userEvent.setup();
    render(<TriageEjemplos />);

    await screen.findByText(EJEMPLO_SEVERIDAD.texto);
    const row = screen.getByText(EJEMPLO_SEVERIDAD.texto).closest('[data-testid="ejemplo-row"]');
    const checkbox = within(row).getByRole('checkbox');
    expect(checkbox).toBeChecked();

    await user.click(checkbox);

    await waitFor(() => expect(api.toggle).toHaveBeenCalled());
    expect(await screen.findByText('Error de red')).toBeInTheDocument();
    expect(checkbox).toBeChecked();
  });
});
