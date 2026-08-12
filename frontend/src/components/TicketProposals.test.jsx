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

/**
 * Covers the topology flip (feat/tickets-triage-aplicar-directo): a
 * `confirmada` proposal with `confirmado_por_id: null` is the AI having
 * ALREADY applied the value — "this was set by the AI, correct it if
 * wrong" — not "approve this suggestion". No Confirm button (nothing left
 * to confirm), Discard reads as a correction, not a rejection of an
 * unapplied guess.
 */
describe('TicketProposals — ia_auto applied values', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso = () => true;
  });

  function aplicada(overrides = {}) {
    return propuesta({
      id: 5,
      campo: 'urgencia',
      valor_propuesto: { valor: 'alta' },
      confianza: 0.91,
      estado: 'confirmada',
      confirmado_por_id: null,
      ...overrides,
    });
  }

  it('shows an already-applied value with a correction affordance, not a Confirm button', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [aplicada()] });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() =>
      expect(screen.getByText((text) => text.includes('Urgencia') && text.includes('alta'))).toBeInTheDocument()
    );
    expect(screen.getByText('Clasificado por IA — corregí si está mal')).toBeInTheDocument();
    expect(screen.getByLabelText(/Descartar Urgencia/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Confirmar Urgencia/i)).not.toBeInTheDocument();
    // No checkbox either — nothing to batch-confirm on an already-applied value.
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('a human-confirmed value (non-null confirmador) never appears here at all', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({
      data: [aplicada({ confirmado_por_id: 7 })],
    });

    const { container } = render(<TicketProposals ticketId={42} />);

    await waitFor(() => expect(ticketsAPI.listarPropuestas).toHaveBeenCalled());
    // Backend never returns human-confirmed rows here — but the frontend's
    // own filter must independently agree: nothing renders.
    expect(container).toBeEmptyDOMElement();
  });

  it('discarding an applied value calls the same descartar endpoint as a pending one, and notifies the parent', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [aplicada()] });
    propuestasAPI.descartar.mockResolvedValue({ data: {} });
    const onChanged = vi.fn();

    render(<TicketProposals ticketId={42} onChanged={onChanged} />);

    await waitFor(() => expect(screen.getByLabelText(/Descartar Urgencia/i)).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText(/Descartar Urgencia/i));

    await waitFor(() => expect(propuestasAPI.descartar).toHaveBeenCalledWith(5));
    // Real pre-push review finding: discarding an ia_auto value now clears
    // it on the ticket — the parent's ticket view must refetch, or it
    // keeps showing the stale value.
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('a field the backend refuses to revert (e.g. titulo) surfaces the inline Spanish error', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({
      data: [aplicada({ id: 9, campo: 'titulo', valor_propuesto: { valor: 'Titulo aplicado por IA' } })],
    });
    propuestasAPI.descartar.mockRejectedValue({
      response: { data: { detail: "No se puede descartar un valor de 'titulo' ya aplicado por la IA" } },
    });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() => expect(screen.getByLabelText(/Descartar Título/i)).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText(/Descartar Título/i));

    await waitFor(() =>
      expect(
        screen.getByText("No se puede descartar un valor de 'titulo' ya aplicado por la IA")
      ).toBeInTheDocument()
    );
  });

  it('pending and already-applied proposals render in separate sections at the same time', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({
      data: [propuesta({ id: 1, campo: 'severidad' }), aplicada({ id: 5, campo: 'urgencia' })],
    });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() => expect(screen.getByText('Propuestas de IA pendientes')).toBeInTheDocument());
    expect(screen.getByText('Clasificado por IA — corregí si está mal')).toBeInTheDocument();
    expect(screen.getByLabelText(/Confirmar Severidad/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Descartar Urgencia/i)).toBeInTheDocument();
    // Only the PENDING item is selectable for batch confirm.
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
  });
});
