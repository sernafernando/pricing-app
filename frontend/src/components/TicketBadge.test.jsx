/**
 * The badge is hidden once the Vikunja sync is on (sdd/tickets-sync-vikunja PR 3).
 *
 * Its count is derived from LOCAL ticket state. The moment triage moves to
 * Vikunja and nothing syncs back, that number is wrong in the direction that
 * matters most: it shows pending work that was already handled, which teaches
 * people to ignore the badge. A counter nobody can act on in this app is worse
 * than no counter — it advertises a panel we are retiring.
 *
 * The flag rides on the badge's OWN count endpoint rather than the sync status
 * endpoint, because every logged-in user renders this badge while that endpoint
 * requires `tickets.gestionar`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../services/api', () => ({
  ticketsAPI: { badgeCount: vi.fn() },
}));

vi.mock('../hooks/useSSEChannel', () => ({ useSSEChannel: () => {} }));
vi.mock('../contexts/SSEContext', () => ({ useSSE: () => ({ isDegraded: () => false }) }));
vi.mock('../contexts/PermisosContext', () => ({ usePermisos: () => ({ tienePermiso: () => true }) }));

import { ticketsAPI } from '../services/api';
import TicketBadge from './TicketBadge';

const BREAKDOWN = {
  pendientes: 4,
  sin_asignar: 2,
  asignados_a_mi: 2,
  asignados_a_otros: 0,
  sin_responder: 0,
  sin_leer: 0,
  con_actividad_nueva: 0,
};

function renderBadge() {
  return render(
    <MemoryRouter>
      <TicketBadge />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('TicketBadge — hidden once Vikunja owns triage', () => {
  it('renders nothing when the sync is enabled', async () => {
    ticketsAPI.badgeCount.mockResolvedValue({
      data: { ...BREAKDOWN, sync_vikunja_habilitado: true },
    });

    const { container } = renderBadge();

    await waitFor(() => expect(ticketsAPI.badgeCount).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it('still renders when the sync is off', async () => {
    ticketsAPI.badgeCount.mockResolvedValue({
      data: { ...BREAKDOWN, sync_vikunja_habilitado: false },
    });

    renderBadge();

    expect(await screen.findByText('4')).toBeInTheDocument();
  });

  it('renders when the field is absent, so an older backend keeps working', async () => {
    ticketsAPI.badgeCount.mockResolvedValue({ data: BREAKDOWN });

    renderBadge();

    expect(await screen.findByText('4')).toBeInTheDocument();
  });
});
