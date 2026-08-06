import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: () => false,
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
    expect(ticketsAPI.listarPropuestas).toHaveBeenCalledWith(42);
  });
});
