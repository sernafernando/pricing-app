import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import TicketsBoard from './TicketsBoard';
import { boardAPI, ticketsAPI } from '../services/api';

/**
 * Covers spec `frontend/tickets-board`:
 * - "Board Grouping by Estado and by Urgencia" (frontend rendering side)
 * - "Overflow uses existing pagination, not a second implementation" —
 *   asserted on REQUEST SHAPE, not just "was called" (per obs #1350's
 *   "layer skipped" lesson: a call assertion without shape is worthless).
 *
 * Known trap (obs #1305/#1350): `user.type()` flakiness in this suite —
 * `fireEvent` used for click interactions, matching TicketProposals.test.jsx.
 */

vi.mock('../services/api', () => ({
  boardAPI: { obtener: vi.fn() },
  ticketsAPI: { listar: vi.fn() },
}));

function card(overrides = {}) {
  return {
    id: 1,
    titulo: 'Ticket de prueba',
    resumen: null,
    severidad: null,
    urgencia: null,
    severidad_origen: null,
    urgencia_origen: null,
    estado: { id: 1, codigo: 'abierto', nombre: 'Abierto', es_final: false },
    sector: { id: 1, codigo: 'soporte', nombre: 'Soporte' },
    created_at: '2026-08-06T10:00:00Z',
    propuestas_pendientes: 0,
    ...overrides,
  };
}

function boardResponse(columnas) {
  return { agrupacion: 'estado', columnas };
}

describe('TicketsBoard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders one column per columnas entry with matching totals', async () => {
    boardAPI.obtener.mockResolvedValue({
      data: boardResponse([
        { clave: '1', etiqueta: 'Abierto', color: '#3b82f6', total: 2, items: [card({ id: 1 }), card({ id: 2 })] },
        { clave: '2', etiqueta: 'Cerrado', color: '#22c55e', total: 0, items: [] },
      ]),
    });

    render(<TicketsBoard agrupacion="estado" onCardClick={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('Abierto')).toBeInTheDocument());
    expect(screen.getByText('Cerrado')).toBeInTheDocument();
    // Totals rendered per column header.
    expect(screen.getAllByText('2')).toHaveLength(1);
    expect(screen.getAllByText('0')).toHaveLength(1);
  });

  it('requests the board with the given agrupacion', async () => {
    boardAPI.obtener.mockResolvedValue({ data: boardResponse([]) });

    render(<TicketsBoard agrupacion="urgencia" onCardClick={vi.fn()} />);

    await waitFor(() => expect(boardAPI.obtener).toHaveBeenCalledWith('urgencia', expect.any(Number)));
  });

  it('"load more" on an estado column calls GET /tickets with estado_id, page and page_size — not a second board query', async () => {
    boardAPI.obtener.mockResolvedValue({
      data: boardResponse([
        { clave: '7', etiqueta: 'Abierto', color: '#3b82f6', total: 5, items: [card({ id: 1 })] },
      ]),
    });
    ticketsAPI.listar.mockResolvedValue({ data: { items: [card({ id: 2 })] } });

    render(<TicketsBoard agrupacion="estado" onCardClick={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('Cargar más')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Cargar más'));

    await waitFor(() => expect(ticketsAPI.listar).toHaveBeenCalledTimes(1));
    expect(ticketsAPI.listar).toHaveBeenCalledWith({ estado_id: '7', page: 2, page_size: expect.any(Number) });
    expect(boardAPI.obtener).toHaveBeenCalledTimes(1); // never a second board query
  });

  it('"load more" on an urgencia column calls GET /tickets with urgencia', async () => {
    boardAPI.obtener.mockResolvedValue({
      data: {
        agrupacion: 'urgencia',
        columnas: [{ clave: 'alta', etiqueta: 'Alta', color: '#f59e0b', total: 5, items: [card({ id: 1 })] }],
      },
    });
    ticketsAPI.listar.mockResolvedValue({ data: { items: [] } });

    render(<TicketsBoard agrupacion="urgencia" onCardClick={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('Cargar más')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Cargar más'));

    await waitFor(() => expect(ticketsAPI.listar).toHaveBeenCalledTimes(1));
    expect(ticketsAPI.listar).toHaveBeenCalledWith({ urgencia: 'alta', page: 2, page_size: expect.any(Number) });
  });

  it('does not offer "load more" when a column has no overflow', async () => {
    boardAPI.obtener.mockResolvedValue({
      data: boardResponse([
        { clave: '1', etiqueta: 'Abierto', color: '#3b82f6', total: 1, items: [card({ id: 1 })] },
      ]),
    });

    render(<TicketsBoard agrupacion="estado" onCardClick={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('Ticket de prueba')).toBeInTheDocument());
    expect(screen.queryByText('Cargar más')).not.toBeInTheDocument();
  });

  it('clicking a card calls onCardClick with its id', async () => {
    const onCardClick = vi.fn();
    boardAPI.obtener.mockResolvedValue({
      data: boardResponse([
        { clave: '1', etiqueta: 'Abierto', color: '#3b82f6', total: 1, items: [card({ id: 55 })] },
      ]),
    });

    render(<TicketsBoard agrupacion="estado" onCardClick={onCardClick} />);

    await waitFor(() => expect(screen.getByText('Ticket de prueba')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Ticket de prueba'));

    expect(onCardClick).toHaveBeenCalledWith(55);
  });
});
