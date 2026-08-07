import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import TicketsBoard from './TicketsBoard';
import { handleDragEnd, moverTicketEntreColumnas } from './ticketsBoardDnd';
import { boardAPI, ticketsAPI } from '../services/api';

/**
 * Covers spec `frontend/tickets-board`:
 * - "Board Grouping by Estado and by Urgencia" (frontend rendering side)
 * - "Overflow uses existing pagination, not a second implementation" —
 *   asserted on REQUEST SHAPE, not just "was called" (per obs #1350's
 *   "layer skipped" lesson: a call assertion without shape is worthless).
 * - "Drag-and-drop write semantics" (PR 5c) — a STATE-column drop transitions
 *   the workflow, a URGENCY-column drop PATCHes urgencia, a same-column drop
 *   is a pure no-op, and a rejected write rolls back with the server's
 *   Spanish detail surfaced.
 *
 * Known trap (obs #1305/#1350): `user.type()` flakiness in this suite —
 * `fireEvent` used for click interactions, matching TicketProposals.test.jsx.
 *
 * HARD CONSTRAINT (this slice's own guard note): dnd-kit drag GESTURES do not
 * work in jsdom. Nothing here simulates a pointer drag. Instead:
 *   1. `handleDragEnd` is imported directly and fed synthetic dnd-kit event
 *      objects for the no-DOM assertions (payload shape, no-op case).
 *   2. For the DOM-visible assertions (rollback + Spanish detail reaching
 *      the screen), `DndContext` is mocked to capture the exact `onDragEnd`
 *      callback `TicketsBoard` wires up internally — the SAME closure that a
 *      real drag would call, bound to the component's REAL state setters.
 *      Calling it is calling `handleDragEnd` with real dependencies, not a
 *      simulated gesture.
 */

vi.mock('../services/api', () => ({
  boardAPI: { obtener: vi.fn() },
  ticketsAPI: { listar: vi.fn(), transicion: vi.fn(), actualizar: vi.fn() },
}));

let capturedOnDragEnd = null;

vi.mock('@dnd-kit/core', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    DndContext: ({ onDragEnd, children }) => {
      capturedOnDragEnd = onDragEnd;
      return children;
    },
  };
});

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

describe('moverTicketEntreColumnas (pure helper)', () => {
  it('moves the ticket from one column to another, adjusting totals', () => {
    const columnas = [
      { clave: '1', etiqueta: 'Abierto', total: 1, items: [card({ id: 1 })] },
      { clave: '2', etiqueta: 'Cerrado', total: 0, items: [] },
    ];

    const resultado = moverTicketEntreColumnas(columnas, 1, '1', '2');

    expect(resultado.find((c) => c.clave === '1').items).toHaveLength(0);
    expect(resultado.find((c) => c.clave === '1').total).toBe(0);
    expect(resultado.find((c) => c.clave === '2').items.map((t) => t.id)).toEqual([1]);
    expect(resultado.find((c) => c.clave === '2').total).toBe(1);
  });

  it('is a no-op when the ticket is not found in the origin column', () => {
    const columnas = [{ clave: '1', etiqueta: 'Abierto', total: 0, items: [] }];

    expect(moverTicketEntreColumnas(columnas, 99, '1', '2')).toBe(columnas);
  });
});

describe('handleDragEnd (pure function, fed synthetic dnd-kit events — no gesture simulated)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function estadoColumnas() {
    return [
      { clave: '1', etiqueta: 'Abierto', total: 1, items: [card({ id: 1 })] },
      { clave: '2', etiqueta: 'Cerrado', total: 0, items: [] },
    ];
  }

  it('dropping on a different STATE column calls transicion with {nuevo_estado_id}, not actualizar', async () => {
    ticketsAPI.transicion.mockResolvedValue({ data: {} });
    const columnas = estadoColumnas();
    const setColumnas = vi.fn();

    await handleDragEnd(
      { active: { id: 'card-1', data: { current: { ticketId: 1, columnaClave: '1' } } }, over: { id: '2' } },
      { columnas, agrupacion: 'estado', setColumnas, onError: vi.fn() }
    );

    expect(ticketsAPI.transicion).toHaveBeenCalledWith(1, { nuevo_estado_id: 2 });
    expect(ticketsAPI.actualizar).not.toHaveBeenCalled();
    // Optimistic move happened before the (mocked-resolved) call settled.
    expect(setColumnas).toHaveBeenCalledWith(moverTicketEntreColumnas(columnas, 1, '1', '2'));
  });

  it('dropping on a different URGENCY column calls actualizar with {urgencia, urgencia_origen: "humano"}, not transicion', async () => {
    ticketsAPI.actualizar.mockResolvedValue({ data: {} });
    const columnas = [
      { clave: 'baja', etiqueta: 'Baja', total: 1, items: [card({ id: 1 })] },
      { clave: 'alta', etiqueta: 'Alta', total: 0, items: [] },
    ];
    const setColumnas = vi.fn();

    await handleDragEnd(
      { active: { id: 'card-1', data: { current: { ticketId: 1, columnaClave: 'baja' } } }, over: { id: 'alta' } },
      { columnas, agrupacion: 'urgencia', setColumnas, onError: vi.fn() }
    );

    expect(ticketsAPI.actualizar).toHaveBeenCalledWith(1, { urgencia: 'alta', urgencia_origen: 'humano' });
    expect(ticketsAPI.transicion).not.toHaveBeenCalled();
  });

  it('dropping on the "sin_clasificar" urgency column sends urgencia: null', async () => {
    ticketsAPI.actualizar.mockResolvedValue({ data: {} });
    const columnas = [
      { clave: 'alta', etiqueta: 'Alta', total: 1, items: [card({ id: 1 })] },
      { clave: 'sin_clasificar', etiqueta: 'Sin clasificar', total: 0, items: [] },
    ];

    await handleDragEnd(
      {
        active: { id: 'card-1', data: { current: { ticketId: 1, columnaClave: 'alta' } } },
        over: { id: 'sin_clasificar' },
      },
      { columnas, agrupacion: 'urgencia', setColumnas: vi.fn(), onError: vi.fn() }
    );

    expect(ticketsAPI.actualizar).toHaveBeenCalledWith(1, { urgencia: null, urgencia_origen: 'humano' });
  });

  it('reordering within the same column makes no API call', async () => {
    const columnas = estadoColumnas();
    const setColumnas = vi.fn();

    await handleDragEnd(
      { active: { id: 'card-1', data: { current: { ticketId: 1, columnaClave: '1' } } }, over: { id: '1' } },
      { columnas, agrupacion: 'estado', setColumnas, onError: vi.fn() }
    );

    expect(ticketsAPI.transicion).not.toHaveBeenCalled();
    expect(ticketsAPI.actualizar).not.toHaveBeenCalled();
    expect(setColumnas).not.toHaveBeenCalled();
  });

  it('a rejected write rolls back the optimistic move and surfaces the server detail', async () => {
    ticketsAPI.transicion.mockRejectedValue({ response: { data: { detail: 'Transición no permitida' } } });
    const columnas = estadoColumnas();
    const setColumnas = vi.fn();
    const onError = vi.fn();

    await handleDragEnd(
      { active: { id: 'card-1', data: { current: { ticketId: 1, columnaClave: '1' } } }, over: { id: '2' } },
      { columnas, agrupacion: 'estado', setColumnas, onError }
    );

    // Second (last) call restores the exact pre-drag snapshot.
    expect(setColumnas).toHaveBeenLastCalledWith(columnas);
    expect(onError).toHaveBeenCalledWith('Transición no permitida');
  });

  it('a rejected write falls back to a generic Spanish message when the server sends none', async () => {
    ticketsAPI.transicion.mockRejectedValue(new Error('network down'));
    const onError = vi.fn();

    await handleDragEnd(
      { active: { id: 'card-1', data: { current: { ticketId: 1, columnaClave: '1' } } }, over: { id: '2' } },
      { columnas: estadoColumnas(), agrupacion: 'estado', setColumnas: vi.fn(), onError }
    );

    expect(onError).toHaveBeenCalledWith('No se pudo mover el ticket');
  });
});

describe('TicketsBoard drag-and-drop (mounted — DndContext mocked to capture the real onDragEnd)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedOnDragEnd = null;
  });

  function estadoBoard() {
    return boardResponse([
      { clave: '1', etiqueta: 'Abierto', color: '#3b82f6', total: 1, items: [card({ id: 1 })] },
      { clave: '2', etiqueta: 'Cerrado', color: '#22c55e', total: 0, items: [] },
    ]);
  }

  it('rolls back the card and shows the server Spanish detail in the DOM on a rejected drop', async () => {
    boardAPI.obtener.mockResolvedValue({ data: estadoBoard() });
    ticketsAPI.transicion.mockRejectedValue({
      response: { data: { detail: 'Transición no permitida desde Abierto' } },
    });

    render(<TicketsBoard agrupacion="estado" onCardClick={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Ticket de prueba')).toBeInTheDocument());
    expect(screen.getAllByText('1')).toHaveLength(1); // Abierto's count
    expect(screen.getAllByText('0')).toHaveLength(1); // Cerrado's count

    await capturedOnDragEnd({
      active: { id: 'card-1', data: { current: { ticketId: 1, columnaClave: '1' } } },
      over: { id: '2' },
    });

    await waitFor(() =>
      expect(screen.getByText('Transición no permitida desde Abierto')).toBeInTheDocument()
    );
    // Counts back to their pre-drag values — the card really rolled back,
    // not just "a catch ran" (obs #1350's "assertion indifferent" trap).
    expect(screen.getAllByText('1')).toHaveLength(1);
    expect(screen.getAllByText('0')).toHaveLength(1);
  });

  it('keeps the moved card and issues no rollback on a successful drop', async () => {
    boardAPI.obtener.mockResolvedValue({ data: estadoBoard() });
    ticketsAPI.transicion.mockResolvedValue({ data: {} });

    render(<TicketsBoard agrupacion="estado" onCardClick={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Ticket de prueba')).toBeInTheDocument());

    await capturedOnDragEnd({
      active: { id: 'card-1', data: { current: { ticketId: 1, columnaClave: '1' } } },
      over: { id: '2' },
    });

    await waitFor(() => expect(screen.getAllByText('1')).toHaveLength(1)); // now Cerrado's count
    expect(screen.getAllByText('0')).toHaveLength(1); // now Abierto's count
    expect(screen.queryByText(/no se pudo|no permitida/i)).not.toBeInTheDocument();
  });
});
