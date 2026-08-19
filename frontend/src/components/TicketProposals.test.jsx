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
    // severidad is correctable (PR2): the plain "Severidad: mayor" text is
    // replaced by the label prefix + SelectorValorPropuesta.
    expect(screen.getByText('Severidad:')).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveValue('mayor');
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
 * Covers spec `frontend/tickets-correction-ui` (tickets-triage-feedback
 * PR2): the value selector wired into the confirm affordance for
 * severidad/urgencia only.
 */
describe('TicketProposals — corrected confirm (PR2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso = () => true;
  });

  it('selecting a different value and confirming sends exactly ONE request carrying the corrected value', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [propuesta()] });
    propuestasAPI.confirmar.mockResolvedValue({ data: {} });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() => expect(screen.getByRole('combobox')).toBeInTheDocument());
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'menor' } });

    fireEvent.click(screen.getByLabelText(/Confirmar severidad/i));

    await waitFor(() => expect(propuestasAPI.confirmar).toHaveBeenCalledTimes(1));
    // Asserts the ARGUMENTS handed to the API layer — the actual request
    // payload shape (`{valor_corregido}`) is proven separately in
    // `api.propuestas.test.js`, per obs #1350's "capa salteada" lesson.
    expect(propuestasAPI.confirmar).toHaveBeenCalledWith(1, 'menor');
  });

  it('confirming without touching the selector sends no corrected value — ratification stays one click', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [propuesta()] });
    propuestasAPI.confirmar.mockResolvedValue({ data: {} });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() => expect(screen.getByRole('combobox')).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText(/Confirmar severidad/i));

    await waitFor(() => expect(propuestasAPI.confirmar).toHaveBeenCalledTimes(1));
    // Exactly ONE argument — no `valor_corregido`, not even `undefined`.
    expect(propuestasAPI.confirmar).toHaveBeenCalledWith(1);
  });

  it('offers exactly the vocabulary for the proposal\'s own campo (urgencia)', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({
      data: [propuesta({ campo: 'urgencia', valor_propuesto: { valor: 'alta' } })],
    });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() => expect(screen.getByRole('combobox')).toBeInTheDocument());
    const opciones = screen.getAllByRole('option').map((o) => o.value);
    expect(opciones).toEqual(['baja', 'normal', 'alta', 'inmediata']);
  });

  it('does not render the selector for a campo the backend cannot correct (titulo)', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({
      data: [propuesta({ campo: 'titulo', valor_propuesto: { valor: 'Falla de fuente' } })],
    });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() =>
      expect(screen.getByText((text) => text.includes('Título') && text.includes('Falla de fuente'))).toBeInTheDocument()
    );
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('a failed corrected confirm surfaces the Spanish detail inline and does not leave the UI claiming success', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [propuesta()] });
    propuestasAPI.confirmar.mockRejectedValue({
      response: { data: { detail: "'urgentisimo' no es un valor válido para severidad" } },
    });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() => expect(screen.getByRole('combobox')).toBeInTheDocument());
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'critica' } });
    fireEvent.click(screen.getByLabelText(/Confirmar severidad/i));

    await waitFor(() =>
      expect(screen.getByText("'urgentisimo' no es un valor válido para severidad")).toBeInTheDocument()
    );
    // Still showing the pending proposal, still defaulted from the AI value
    // — never re-fetched into a false "confirmed" state after a rejection.
    expect(screen.getByRole('combobox')).toBeInTheDocument();
    expect(ticketsAPI.listarPropuestas).toHaveBeenCalledTimes(1);
  });
});

/**
 * Covers the topology flip (feat/tickets-triage-aplicar-directo): a
 * `confirmada` proposal with `confirmado_por_id: null` is the AI having
 * ALREADY applied the value — "this was set by the AI, correct it if
 * wrong" — not "approve this suggestion". Confirm here RATIFIES (marks
 * reviewed, never rewrites the ticket — the value is already there, real
 * pre-push review finding: without it, a non-revertible field had no exit
 * from "unreviewed" at all); Discard CORRECTS, only where
 * CAMPOS_REVERTIBLES allows a clean revert.
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

  it('shows an already-applied value with BOTH a ratify (Confirm) and a correction (Discard) affordance', async () => {
    // Real pre-push review finding (BLOCKING): a Confirm without any
    // pre-existing value would "approve a suggestion" — here it means "I
    // looked, this is fine" (ratify), which never rewrites the ticket.
    // Discard still means "correct it", only for CAMPOS_REVERTIBLES.
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [aplicada()] });

    render(<TicketProposals ticketId={42} />);

    // urgencia is correctable (PR2): the selector replaces the plain
    // "Urgencia: alta" text, defaulted to the AI-applied value.
    await waitFor(() => expect(screen.getByText('Urgencia:')).toBeInTheDocument());
    expect(screen.getByRole('combobox')).toHaveValue('alta');
    expect(screen.getByText('Clasificado por IA — corregí si está mal')).toBeInTheDocument();
    expect(screen.getByLabelText(/Confirmar Urgencia/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Descartar Urgencia/i)).toBeInTheDocument();
    // No checkbox either — nothing to batch-confirm on an already-applied value.
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('ratifying an already-applied value calls confirmar (not descartar) and notifies the parent', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [aplicada()] });
    propuestasAPI.confirmar.mockResolvedValue({ data: {} });
    const onChanged = vi.fn();

    render(<TicketProposals ticketId={42} onChanged={onChanged} />);

    await waitFor(() => expect(screen.getByLabelText(/Confirmar Urgencia/i)).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText(/Confirmar Urgencia/i));

    await waitFor(() => expect(propuestasAPI.confirmar).toHaveBeenCalledWith(5));
    expect(propuestasAPI.descartar).not.toHaveBeenCalled();
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
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

  it('does not offer Discard for a field the backend cannot revert (e.g. titulo) — Confirm (ratify) still works', async () => {
    // Real pre-push review finding (BLOCKING, two parts):
    // 1. `descartar()` only reverts CAMPOS_REVERTIBLES (severidad/
    //    urgencia/resumen) — titulo/sector/tipo_ticket/metadata_ia raise a
    //    409. Offering a Discard button guaranteed to fail is a broken
    //    affordance, so it must not render for these fields.
    // 2. Without ratify, a non-revertible field had NO way to ever leave
    //    "unreviewed" — Confirm now ratifies it (sets confirmado_por_id
    //    without rewriting the ticket), closing that gap.
    ticketsAPI.listarPropuestas.mockResolvedValue({
      data: [aplicada({ id: 9, campo: 'titulo', valor_propuesto: { valor: 'Titulo aplicado por IA' } })],
    });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() =>
      expect(screen.getByText((text) => text.includes('Título') && text.includes('Titulo aplicado por IA'))).toBeInTheDocument()
    );
    expect(screen.queryByLabelText(/Descartar Título/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Confirmar Título/i)).toBeInTheDocument();
    expect(propuestasAPI.descartar).not.toHaveBeenCalled();
  });

  it('does not offer Discard for sector either — same non-revertible set as titulo, Confirm still ratifies it', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({
      data: [aplicada({ id: 10, campo: 'sector', valor_propuesto: { valor: 'Ventas' } })],
    });
    propuestasAPI.confirmar.mockResolvedValue({ data: {} });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() =>
      expect(screen.getByText((text) => text.includes('Sector') && text.includes('Ventas'))).toBeInTheDocument()
    );
    expect(screen.queryByLabelText(/Descartar Sector/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Confirmar Sector/i)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Confirmar Sector/i));
    await waitFor(() => expect(propuestasAPI.confirmar).toHaveBeenCalledWith(10));
  });

  it('pending and already-applied proposals render in separate sections at the same time', async () => {
    ticketsAPI.listarPropuestas.mockResolvedValue({
      data: [propuesta({ id: 1, campo: 'severidad' }), aplicada({ id: 5, campo: 'urgencia' })],
    });

    render(<TicketProposals ticketId={42} />);

    await waitFor(() => expect(screen.getByText('Propuestas de IA pendientes')).toBeInTheDocument());
    expect(screen.getByText('Clasificado por IA — corregí si está mal')).toBeInTheDocument();
    expect(screen.getByLabelText(/Confirmar Severidad/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Confirmar Urgencia/i)).toBeInTheDocument(); // ratify, aplicada section
    expect(screen.getByLabelText(/Descartar Urgencia/i)).toBeInTheDocument();
    // Only the PENDING item is selectable for batch confirm.
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
  });
});
