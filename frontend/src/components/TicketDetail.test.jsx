import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import TicketDetail from './TicketDetail';
import { ticketsAPI } from '../services/api';

/**
 * Regression coverage for the `marcarRevisado` path fix (PR
 * fix/tickets-workflow-enforcement). `ticketsAPI.marcarRevisado` is called
 * from `fetchTicket`'s non-blocking `catch` (TicketDetail.jsx:147-151),
 * which previously masked the 404 caused by the missing double `/tickets`
 * segment in `services/api.js`. These tests lock in:
 *   1. `marcarRevisado` is actually invoked for the loaded ticket.
 *   2. The catch staying non-blocking is intentional — a rejection from
 *      `marcarRevisado` must NOT prevent the ticket detail from rendering.
 *
 * PermisosContext and useSSEChannel are mocked locally (overriding the
 * global setup.js stub), and services/api is mocked locally with the
 * ticketsAPI/sectoresAPI shape this component actually uses.
 */

vi.mock('../services/api', () => ({
  ticketsAPI: {
    obtener: vi.fn(),
    marcarRevisado: vi.fn(),
    listarComentarios: vi.fn().mockResolvedValue({ data: [] }),
    obtenerHistorial: vi.fn().mockResolvedValue({ data: [] }),
    listarAdjuntos: vi.fn().mockResolvedValue({ data: [] }),
    listarPropuestas: vi.fn().mockResolvedValue({ data: [] }),
    triage: vi.fn(),
  },
  sectoresAPI: {
    listarWorkflows: vi.fn().mockResolvedValue({ data: [] }),
    listarUsuarios: vi.fn().mockResolvedValue({ data: [] }),
  },
  propuestasAPI: {
    confirmar: vi.fn(),
    descartar: vi.fn(),
    confirmarBatch: vi.fn(),
  },
}));

let mockTienePermiso = () => false;
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (codigo) => mockTienePermiso(codigo),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../hooks/useSSEChannel', () => ({
  useSSEChannel: vi.fn(),
}));

function baseTicket(overrides = {}) {
  return {
    id: 42,
    titulo: 'No puedo facturar desde ayer',
    descripcion: 'Detalle del problema',
    prioridad: 'MEDIA',
    estado: { id: 1, nombre: 'Abierto', color: '#3b82f6' },
    sector: { id: 1, nombre: 'Soporte' },
    tipo_ticket: { id: 1, nombre: 'Consulta' },
    creador: { id: 1, nombre: 'Reportante' },
    asignado_a: null,
    created_at: '2026-08-01T10:00:00Z',
    closed_at: null,
    esta_cerrado: false,
    metadata: {},
    ...overrides,
  };
}

describe('TicketDetail — marcarRevisado non-blocking catch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso = () => false;
  });

  it('calls ticketsAPI.marcarRevisado with the loaded ticket id', async () => {
    ticketsAPI.obtener.mockResolvedValue({ data: baseTicket() });
    ticketsAPI.marcarRevisado.mockResolvedValue({ data: { ok: true } });

    render(<TicketDetail ticketId={42} onClose={() => {}} />);

    await waitFor(() => expect(ticketsAPI.marcarRevisado).toHaveBeenCalledWith(42));
  });

  it('still renders the ticket when marcarRevisado rejects (e.g. a 404)', async () => {
    ticketsAPI.obtener.mockResolvedValue({ data: baseTicket() });
    ticketsAPI.marcarRevisado.mockRejectedValue({
      response: { status: 404, data: { detail: 'Not Found' } },
    });

    render(<TicketDetail ticketId={42} onClose={() => {}} />);

    // The ticket title must render — a rejected marcarRevisado call must
    // never block or fail the ticket detail view.
    await waitFor(() => expect(screen.getByText('No puedo facturar desde ayer')).toBeInTheDocument());
    expect(screen.queryByText('Error al cargar el ticket')).not.toBeInTheDocument();
  });
});

describe('TicketDetail — AI triage provenance (tickets-ai-triage PR 4c)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso = () => false;
  });

  it('shows a provenance badge for an AI-confirmed severidad and fetches pending proposals for the ticket', async () => {
    ticketsAPI.obtener.mockResolvedValue({
      data: baseTicket({ severidad: 'mayor', severidad_origen: 'ia_confirmada' }),
    });
    ticketsAPI.marcarRevisado.mockResolvedValue({ data: { ok: true } });
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [] });

    render(<TicketDetail ticketId={42} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText('mayor')).toBeInTheDocument());
    expect(screen.getByText('IA confirmada')).toBeInTheDocument();

    // Separate await: the ticket rendering above is driven by `obtener`, while
    // the proposals come from an independent `listarPropuestas` call. Asserting
    // it synchronously here only passed because both promises usually settle in
    // the same flush — under CI load they do not, and this failed with 0 calls.
    await waitFor(() => expect(ticketsAPI.listarPropuestas).toHaveBeenCalledWith(42));
  });
});

describe('TicketDetail — AI triage retrigger button (fix/tickets-triage-backfill)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    ticketsAPI.obtener.mockResolvedValue({ data: baseTicket() });
    ticketsAPI.marcarRevisado.mockResolvedValue({ data: { ok: true } });
    ticketsAPI.listarPropuestas.mockResolvedValue({ data: [] });
  });

  it('is absent without tickets.triage.confirmar', async () => {
    mockTienePermiso = () => false;

    render(<TicketDetail ticketId={42} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText('No puedo facturar desde ayer')).toBeInTheDocument());
    expect(screen.queryByText(/Reintentar triage de IA/i)).not.toBeInTheDocument();
  });

  it('calls ticketsAPI.triage with only the ticket id when clicked (forzar is never exposed here)', async () => {
    mockTienePermiso = (codigo) => codigo === 'tickets.triage.confirmar';
    ticketsAPI.triage.mockResolvedValue({ data: { ok: true } });

    render(<TicketDetail ticketId={42} onClose={() => {}} />);

    const boton = await screen.findByText(/Reintentar triage de IA/i);
    fireEvent.click(boton);

    await waitFor(() => expect(ticketsAPI.triage).toHaveBeenCalledTimes(1));
    expect(ticketsAPI.triage).toHaveBeenCalledWith(42);
  });

  it('refetches proposals a few seconds after a successful retrigger (the promised update actually happens)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockTienePermiso = (codigo) => codigo === 'tickets.triage.confirmar';
    ticketsAPI.triage.mockResolvedValue({ data: { ok: true } });

    render(<TicketDetail ticketId={42} onClose={() => {}} />);

    const boton = await screen.findByText(/Reintentar triage de IA/i);
    fireEvent.click(boton);

    await waitFor(() => expect(ticketsAPI.triage).toHaveBeenCalledTimes(1));
    // One call on mount — the delayed refresh has not fired yet.
    expect(ticketsAPI.listarPropuestas).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(4000);

    await waitFor(() => expect(ticketsAPI.listarPropuestas).toHaveBeenCalledTimes(2));
    vi.useRealTimers();
  });

  it('a 409 (proposals already exist) surfaces the server Spanish detail inline', async () => {
    mockTienePermiso = (codigo) => codigo === 'tickets.triage.confirmar';
    ticketsAPI.triage.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: 'Ya existe una clasificación pendiente o confirmada para este ticket; use forzar=true para reintentar' },
      },
    });

    render(<TicketDetail ticketId={42} onClose={() => {}} />);

    const boton = await screen.findByText(/Reintentar triage de IA/i);
    fireEvent.click(boton);

    await waitFor(() =>
      expect(
        screen.getByText('Ya existe una clasificación pendiente o confirmada para este ticket; use forzar=true para reintentar')
      ).toBeInTheDocument()
    );
  });
});
