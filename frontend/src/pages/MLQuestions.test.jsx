/**
 * Tests for the "Mensajes" (ML Bot postventa messages) tab added to
 * MLQuestions.jsx (PR3, Phase 5).
 *
 * Scope (per apply instructions):
 *   - Tab visibility gated by `ml_bot.messages.ver` (puedeVerMensajes)
 *   - GET /ml-bot/messages called with correct query params when filters apply
 *
 * PermisosContext and useSSEChannel are mocked locally (overriding the
 * global setup.js stub) so each test can control tienePermiso per-case.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MLQuestions from './MLQuestions';
import api from '../services/api';

const mockTienePermiso = vi.fn(() => true);

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

function setupBaseApiMocks() {
  api.get.mockImplementation((url) => {
    if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
    if (url === '/ml-bot/questions') return Promise.resolve({ data: { questions: [] } });
    if (url === '/ml-bot/messages') return Promise.resolve({ data: { messages: [], total: 0 } });
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  mockTienePermiso.mockReset();
  mockTienePermiso.mockImplementation(() => true);
  setupBaseApiMocks();
});

describe('Mensajes tab visibility', () => {
  it('shows the "Mensajes" tab when ml_bot.messages.ver is granted', async () => {
    mockTienePermiso.mockImplementation(() => true);

    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Mensajes/i })).toBeInTheDocument();
    });
  });

  it('hides the "Mensajes" tab when ml_bot.messages.ver is not granted', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'ml_bot.messages.ver');

    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText('Preguntas')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /Mensajes/i })).not.toBeInTheDocument();
  });
});

describe('Mensajes tab filters -> GET /ml-bot/messages params', () => {
  it('calls GET /ml-bot/messages with buyer_id, pack_id=none, has_read and include_moderated when filters applied', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    const tabButton = await screen.findByRole('button', { name: /Mensajes/i });
    await user.click(tabButton);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-bot/messages', expect.anything());
    });

    // Buyer filter
    const buyerInput = screen.getByPlaceholderText(/comprador/i);
    await user.type(buyerInput, '12345');

    // "Sin pack" chip toggles pack_id=none
    const sinPackChip = screen.getByRole('button', { name: /sin pack/i });
    await user.click(sinPackChip);

    // include_moderated toggle
    const moderatedToggle = screen.getByLabelText(/incluir moderados/i);
    await user.click(moderatedToggle);

    // has_read toggle
    const hasReadToggle = screen.getByLabelText(/le[íi]d[oa]s?/i);
    await user.click(hasReadToggle);

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/messages');
      const last = calls[calls.length - 1];
      expect(last[1].params).toEqual(
        expect.objectContaining({
          buyer_id: '12345',
          pack_id: 'none',
          include_moderated: true,
        })
      );
      expect(last[1].params).toHaveProperty('has_read');
    });
  });
});
