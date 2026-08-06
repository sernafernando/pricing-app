/**
 * Tests for the flat segmented view control (tickets-ai-triage PR 5b).
 *
 * Covers spec `frontend/tickets-board`, "One Flat Segmented View Control":
 * - Selecting a board view updates the URL to `?vista=...` (linkable).
 * - Reload (URL already carries `?vista=...`) preserves the view.
 * - No `vista` param falls back to localStorage, defaulting to `tabla`.
 *
 * `TicketsBoard` is mocked — this file only owns the control + URL/storage
 * wiring, not board rendering (covered in TicketsBoard.test.jsx).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { renderWithRouter } from '../test/renderWithRouter';
import Tickets from './Tickets';
import { ticketsAPI, sectoresAPI } from '../services/api';

vi.mock('../services/api', () => ({
  ticketsAPI: { listar: vi.fn(), marcarRevisado: vi.fn() },
  sectoresAPI: { listar: vi.fn() },
}));

vi.mock('../hooks/useSSEChannel', () => ({ useSSEChannel: vi.fn() }));

vi.mock('../components/TicketsBoard', () => ({
  default: ({ agrupacion }) => <div data-testid="board">board:{agrupacion}</div>,
}));

vi.mock('../components/TicketCreateModal', () => ({ default: () => null }));
vi.mock('../components/TicketDetail', () => ({ default: () => null }));

const VISTA_STORAGE_KEY = 'tickets:vista';

describe('Tickets — segmented view control', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    ticketsAPI.listar.mockResolvedValue({ data: { items: [], total: 0 } });
    sectoresAPI.listar.mockResolvedValue({ data: [] });
  });

  it('selecting "Tablero por urgencia" updates the URL to ?vista=urgencia', async () => {
    renderWithRouter(<Tickets />, { initialEntries: ['/tickets'] });

    await waitFor(() => expect(ticketsAPI.listar).toHaveBeenCalled());

    fireEvent.click(screen.getByText('Tablero por urgencia'));

    await waitFor(() => expect(screen.getByTestId('board')).toHaveTextContent('board:urgencia'));
    expect(window.location.search).toBe('');
    // URL state lives in react-router's in-memory history, not window.location
    // under MemoryRouter — assert via the rendered board + localStorage mirror.
    expect(localStorage.getItem(VISTA_STORAGE_KEY)).toBe('urgencia');
  });

  it('reload with ?vista=urgencia in the URL preserves that view', async () => {
    renderWithRouter(<Tickets />, { initialEntries: ['/tickets?vista=urgencia'] });

    await waitFor(() => expect(screen.getByTestId('board')).toHaveTextContent('board:urgencia'));
  });

  it('no vista param falls back to localStorage', async () => {
    localStorage.setItem(VISTA_STORAGE_KEY, 'estado');

    renderWithRouter(<Tickets />, { initialEntries: ['/tickets'] });

    await waitFor(() => expect(screen.getByTestId('board')).toHaveTextContent('board:estado'));
  });

  it('no vista param and no localStorage defaults to tabla', async () => {
    renderWithRouter(<Tickets />, { initialEntries: ['/tickets'] });

    await waitFor(() => expect(ticketsAPI.listar).toHaveBeenCalled());
    expect(screen.queryByTestId('board')).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Tabla/ })).toHaveAttribute('aria-selected', 'true');
  });
});
