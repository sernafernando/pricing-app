import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import TicketProposals from './TicketProposals';
import { ticketsAPI, propuestasAPI } from '../services/api';

/**
 * Covers spec `frontend/tickets-board`:
 * - "Confidence is visible before confirming"
 * - "Multi-select confirms in one request"
 * - "Confirm without permission is rejected" (UI side: controls hidden)
 * - Failure path: a rejected confirm surfaces an inline Spanish error and
 *   does not leave the UI claiming success.
 *
 * Known trap from this chain (per apply-progress obs #1350/#1305):
 * `user.type()` has shown flakiness in this suite; `fireEvent` is used
 * instead for checkbox/button interactions, matching the workaround already
 * used elsewhere (e.g. TicketCreateModal.test.jsx).
 */

vi.mock('../services/api', () => ({
  ticketsAPI: {
    listarPropuestas: vi.fn(),
  },
  propuestasAPI: {
    confirmar: vi.fn(),
    descartar: vi.fn(),
    confirmarBatch: vi.fn(),
  },
}));

let mockTienePermiso = () => true;
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (codigo) => mockTienePermiso(codigo) }),
  PermisosProvider: ({ children }) => children,
}));

function propuesta(overrides = {}) {
  return {
    id: 1,
    ticket_id: 42,
    campo: 'severidad',
    valor_propuesto: { valor: 'mayor' },
    confianza: 0.82,
    modelo: 'llama-3.3-70b-versatile',
    estado: 'pendiente',
    confirmado_por_id: null,
    confirmado_at: null,
    created_at: '2026-08-06T10:00:00Z',
    ...overrides,
  };
}

describe('TicketProposals', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso = () => true;
  });

  it('shows confidence on the confirm affordance before anything is confirmed', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [propuesta()] });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() =>
      expect(screen.getByText((text) => text.includes('IA 0.82'))).toBeInTheDocument()
    );
    expect(screen.getByText((text) => text.includes('Severidad') && text.includes('mayor'))).toBeInTheDocument();
    expect(propuestasAPI.confirmar).not.toHaveBeenCalled();
  });

  it('selecting several proposals and confirming sends exactly ONE batch request with all ids', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({
      data: [propuesta({ id: 1, campo: 'severidad' }), propuesta({ id: 2, campo: 'urgencia', confianza: 0.91 })],
    });
    propuestasAPI.confirmarBatch.mockResolvedValue({ data: [] });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() => expect(screen.getAllByRole('checkbox')).toHaveLength(2));
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    fireEvent.click(screen.getByText(/Confirmar seleccionadas/));

    await waitFor(() => expect(propuestasAPI.confirmarBatch).toHaveBeenCalledTimes(1));
    expect(propuestasAPI.confirmarBatch).toHaveBeenCalledWith([1, 2]);
    // Never falls back to N single confirms when a batch was requested.
    expect(propuestasAPI.confirmar).not.toHaveBeenCalled();
  });

  it('hides confirm/discard controls without tickets.triage.confirmar, but keeps confidence visible', async () => {
    mockTienePermiso = () => false;
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [propuesta()] });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() =>
      expect(screen.getByText((text) => text.includes('IA 0.82'))).toBeInTheDocument()
    );
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Confirmar severidad/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Descartar severidad/i)).not.toBeInTheDocument();
  });

  it('a rejected confirm surfaces an inline Spanish error and does not claim success', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [propuesta()] });
    propuestasAPI.confirmar.mockRejectedValue({
      response: { data: { detail: 'La propuesta ya no está pendiente' } },
    });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() => expect(screen.getByLabelText(/Confirmar severidad/i)).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText(/Confirmar severidad/i));

    await waitFor(() =>
      expect(screen.getByText('La propuesta ya no está pendiente')).toBeInTheDocument()
    );
    // Still showing the pending proposal — never re-fetched into a false
    // "confirmed" state after a rejection.
    expect(screen.getByText((text) => text.includes('IA 0.82'))).toBeInTheDocument();
    expect(ticketsAPI.listarPropuestas).toHaveBeenCalledTimes(1);
  });

  it('renders nothing when there are no pending proposals', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [] });

    const { container } = render(<TicketProposals ticketId={42} />);

    await waitFor(() => expect(ticketsAPI.listarPropuestas).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
