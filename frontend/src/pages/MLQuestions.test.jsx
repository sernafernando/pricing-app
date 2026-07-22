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
import MLQuestions, { loadColumnSizing, saveColumnSizing } from './MLQuestions';
import api from '../services/api';

const COLUMN_SIZING_KEY = 'mlq:colsizing:preguntas';

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

describe('Mensajes tab threading (grouping by pack_id + buyer_id)', () => {
  it('groups messages of the same pack under one thread header', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
      if (url === '/ml-bot/questions') return Promise.resolve({ data: { questions: [] } });
      if (url === '/ml-bot/messages') {
        return Promise.resolve({
          data: {
            messages: [
              {
                id: 1,
                ml_message_id: 'msg-a',
                pack_id: '2000013868175593',
                buyer_id: 173555877,
                buyer_nickname: 'JUAN_PEREZ',
                text: 'Buen día me pasas la factura',
                received_at: '2026-07-10T14:57:25Z',
                read_at: null,
                moderation_status: 'clean',
              },
              {
                id: 2,
                ml_message_id: 'msg-b',
                pack_id: '2000013868175593',
                buyer_id: 173555877,
                buyer_nickname: 'JUAN_PEREZ',
                text: 'Es factura A',
                received_at: '2026-07-10T14:58:00Z',
                read_at: null,
                moderation_status: 'clean',
              },
              {
                id: 3,
                ml_message_id: 'msg-c',
                pack_id: '2000017320250138',
                buyer_id: 85885085,
                buyer_nickname: 'MARIA_LOPEZ',
                text: 'Solicito factura A. Gracias',
                received_at: '2026-07-10T15:11:11Z',
                read_at: null,
                moderation_status: 'clean',
              },
            ],
            total: 3,
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    const tabButton = await screen.findByRole('button', { name: /Mensajes/i });
    await user.click(tabButton);

    await waitFor(() => {
      expect(screen.getByText(/JUAN_PEREZ/)).toBeInTheDocument();
      expect(screen.getByText(/MARIA_LOPEZ/)).toBeInTheDocument();
    });

    // JUAN_PEREZ header should announce "2 mensajes" (grouped), MARIA_LOPEZ "1 mensaje"
    expect(screen.getByText(/2 mensajes/)).toBeInTheDocument();
    expect(screen.getByText(/1 mensaje$/)).toBeInTheDocument();
    // All three message texts render
    expect(screen.getByText('Buen día me pasas la factura')).toBeInTheDocument();
    expect(screen.getByText('Es factura A')).toBeInTheDocument();
    expect(screen.getByText('Solicito factura A. Gracias')).toBeInTheDocument();
  });
});

describe('Preguntas table — column-sizing persistence (loadColumnSizing/saveColumnSizing)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns {} when the key is absent', () => {
    expect(loadColumnSizing(COLUMN_SIZING_KEY)).toEqual({});
  });

  it('returns {} (never throws) when the stored value is corrupt JSON', () => {
    localStorage.setItem(COLUMN_SIZING_KEY, '{not valid json');
    expect(() => loadColumnSizing(COLUMN_SIZING_KEY)).not.toThrow();
    expect(loadColumnSizing(COLUMN_SIZING_KEY)).toEqual({});
  });

  it('round-trips a valid columnSizing object', () => {
    const sizing = { pregunta: 200, item: 130 };
    saveColumnSizing(sizing, COLUMN_SIZING_KEY);
    expect(loadColumnSizing(COLUMN_SIZING_KEY)).toEqual(sizing);
  });

  it('ignores unknown/stale column ids on load (fail-open, still an object)', () => {
    localStorage.setItem(COLUMN_SIZING_KEY, JSON.stringify({ pregunta: 200, columnaFantasma: 999 }));
    const loaded = loadColumnSizing(COLUMN_SIZING_KEY);
    // Loader itself doesn't filter by known ids (TanStack ignores unknown ids
    // at consumption time) — assert it still returns a safe plain object.
    expect(loaded).toEqual({ pregunta: 200, columnaFantasma: 999 });
  });

  it('saveColumnSizing never throws when localStorage.setItem throws', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    expect(() => saveColumnSizing({ pregunta: 200 }, COLUMN_SIZING_KEY)).not.toThrow();
    spy.mockRestore();
  });
});

describe('Preguntas table — TanStack column-sizing render structure', () => {
  it('renders one <col> per header and resize grips only on resizable headers', async () => {
    localStorage.clear();
    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText('Pregunta')).toBeInTheDocument();
    });

    const table = screen.getByText('Pregunta').closest('table');
    const cols = table.querySelectorAll('colgroup > col');
    const headers = table.querySelectorAll('thead th');
    expect(cols.length).toBe(headers.length);
    expect(cols.length).toBe(7);

    // Resizable: Pregunta, Item, Respuesta (borrador). Fixed: Estado,
    // Confianza, Cuenta regresiva, Acciones.
    const grips = table.querySelectorAll('thead [role="separator"]');
    expect(grips.length).toBe(3);
  });

  it('shows the reset-columns control only once sizing has been customized', async () => {
    localStorage.clear();
    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText('Pregunta')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /restablecer columnas/i })).not.toBeInTheDocument();
  });

  it('mounts with a previously persisted custom width and shows the reset control', async () => {
    localStorage.setItem(COLUMN_SIZING_KEY, JSON.stringify({ pregunta: 250 }));
    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /restablecer columnas/i })).toBeInTheDocument();
    });
    localStorage.clear();
  });
});
