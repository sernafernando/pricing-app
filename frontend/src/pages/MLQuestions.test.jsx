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
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MLQuestions, { loadColumnSizing, saveColumnSizing } from './MLQuestions';
import api from '../services/api';

const COLUMN_SIZING_KEY = 'mlq:colsizing:preguntas';
const HISTORIAL_COLUMN_SIZING_KEY = 'mlq:colsizing:historial';
const MENSAJES_COLUMN_SIZING_KEY = 'mlq:colsizing:mensajes';

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
  // Reset to a harmless default on every test — `vi.clearAllMocks()` (in the
  // shared setup.js) only clears call history, NOT `mockImplementation`, so
  // a test-local `api.post.mockImplementation(...)` (e.g. the `sent: false`
  // cases below) would otherwise leak into every later test in this file.
  api.post.mockImplementation(() => Promise.resolve({ data: {} }));
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

    // Thread grouping structure survives the new <colgroup>: header row
    // colSpan=5, each message row has 5 cells (thin indent + mensaje +
    // recibido + leido + moderacion).
    const table = screen.getByText(/JUAN_PEREZ/).closest('table');
    const headerCell = screen.getByText(/JUAN_PEREZ/).closest('td');
    expect(headerCell).toHaveAttribute('colspan', '5');
    const messageRow = screen.getByText('Buen día me pasas la factura').closest('tr');
    expect(messageRow.querySelectorAll('td').length).toBe(5);
    const cols = table.querySelectorAll('colgroup > col');
    expect(cols.length).toBe(5);
  });
});

describe('Mensajes table — column-sizing persistence (loadColumnSizing/saveColumnSizing)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns {} when the key is absent', () => {
    expect(loadColumnSizing(MENSAJES_COLUMN_SIZING_KEY)).toEqual({});
  });

  it('returns {} (never throws) when the stored value is corrupt JSON', () => {
    localStorage.setItem(MENSAJES_COLUMN_SIZING_KEY, '{not valid json');
    expect(() => loadColumnSizing(MENSAJES_COLUMN_SIZING_KEY)).not.toThrow();
    expect(loadColumnSizing(MENSAJES_COLUMN_SIZING_KEY)).toEqual({});
  });

  it('round-trips a valid columnSizing object under its own key', () => {
    const sizing = { mensaje: 380 };
    saveColumnSizing(sizing, MENSAJES_COLUMN_SIZING_KEY);
    expect(loadColumnSizing(MENSAJES_COLUMN_SIZING_KEY)).toEqual(sizing);
  });
});

describe('Mensajes table — TanStack column-sizing render structure', () => {
  it('renders one <col> per header and a resize grip only on "Mensaje" (Comprador · Pack is not resizable)', async () => {
    localStorage.clear();
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    const tabButton = await screen.findByRole('button', { name: /Mensajes/i });
    await user.click(tabButton);

    await waitFor(() => {
      expect(screen.getByText('Mensaje')).toBeInTheDocument();
    });

    const table = screen.getByText('Mensaje').closest('table');
    const cols = table.querySelectorAll('colgroup > col');
    const headers = table.querySelectorAll('thead th');
    expect(cols.length).toBe(headers.length);
    expect(cols.length).toBe(5);

    // Only "Mensaje" is resizable — "Comprador · Pack" has no identity in
    // per-message rows (thin indent cell only), so it stays fixed-width.
    const grips = table.querySelectorAll('thead [role="separator"]');
    expect(grips.length).toBe(1);
  });

  it('shows the reset-columns control only once sizing has been customized', async () => {
    localStorage.clear();
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    const tabButton = await screen.findByRole('button', { name: /Mensajes/i });
    await user.click(tabButton);

    await waitFor(() => {
      expect(screen.getByText('Mensaje')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /restablecer columnas/i })).not.toBeInTheDocument();
  });

  it('mounts with a previously persisted custom width and shows the reset control', async () => {
    localStorage.setItem(MENSAJES_COLUMN_SIZING_KEY, JSON.stringify({ mensaje: 400 }));
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    const tabButton = await screen.findByRole('button', { name: /Mensajes/i });
    await user.click(tabButton);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /restablecer columnas/i })).toBeInTheDocument();
    });
    localStorage.clear();
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

describe('Historial del comprador table — column-sizing persistence', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('round-trips a valid columnSizing object under its own key', () => {
    const sizing = { pregunta: 220, item: 130 };
    saveColumnSizing(sizing, HISTORIAL_COLUMN_SIZING_KEY);
    expect(loadColumnSizing(HISTORIAL_COLUMN_SIZING_KEY)).toEqual(sizing);
  });

  it('returns {} (never throws) when the stored value is corrupt JSON', () => {
    localStorage.setItem(HISTORIAL_COLUMN_SIZING_KEY, '{not valid json');
    expect(() => loadColumnSizing(HISTORIAL_COLUMN_SIZING_KEY)).not.toThrow();
    expect(loadColumnSizing(HISTORIAL_COLUMN_SIZING_KEY)).toEqual({});
  });
});

describe('Historial del comprador table — TanStack column-sizing render structure', () => {
  function mockWithHistory() {
    api.get.mockImplementation((url) => {
      if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
      if (url === '/ml-bot/questions') {
        return Promise.resolve({
          data: {
            questions: [
              {
                id: 1,
                question_text: 'Hola, tienen stock?',
                item_id: 'MLA123',
                status: 'received',
                buyer_id: 555,
                buyer_nickname: 'COMPRADOR_1',
              },
            ],
          },
        });
      }
      if (url === '/ml-bot/questions/1/buyer-history') {
        return Promise.resolve({
          data: {
            questions: [
              {
                id: 99,
                question_date: '2026-07-01T10:00:00Z',
                question_text: 'Pregunta anterior',
                item_title: 'Producto anterior',
                status: 'published',
                drafted_answer: 'Sí, tenemos stock',
              },
            ],
          },
        });
      }
      return Promise.resolve({ data: {} });
    });
  }

  it('renders one <col> per header and resize grips only on resizable headers', async () => {
    localStorage.clear();
    mockWithHistory();
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText('Hola, tienen stock?')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /ver detalle completo/i }));
    await user.click(screen.getByText('Historial del comprador'));

    await waitFor(() => {
      expect(screen.getByText('Pregunta anterior')).toBeInTheDocument();
    });

    const table = screen.getByText('Pregunta anterior').closest('table');
    const cols = table.querySelectorAll('colgroup > col');
    const headers = table.querySelectorAll('thead th');
    expect(cols.length).toBe(headers.length);
    expect(cols.length).toBe(5);

    // Resizable: Pregunta, Item, Respuesta. Fixed: Fecha, Estado.
    const grips = table.querySelectorAll('thead [role="separator"]');
    expect(grips.length).toBe(3);
  });

  it('shows the reset-columns control only once sizing has been customized', async () => {
    localStorage.clear();
    mockWithHistory();
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText('Hola, tienen stock?')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /ver detalle completo/i }));
    await user.click(screen.getByText('Historial del comprador'));

    await waitFor(() => {
      expect(screen.getByText('Pregunta anterior')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /restablecer columnas/i })).not.toBeInTheDocument();
  });

  it('mounts with a previously persisted custom width and shows the reset control', async () => {
    localStorage.setItem(HISTORIAL_COLUMN_SIZING_KEY, JSON.stringify({ pregunta: 260 }));
    mockWithHistory();
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText('Hola, tienen stock?')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /ver detalle completo/i }));
    await user.click(screen.getByText('Historial del comprador'));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /restablecer columnas/i })).toBeInTheDocument();
    });
    localStorage.clear();
  });
});

// ---------------------------------------------------------------------------
// Mensajes tab — thread actions (take-over/edit/send), claim badge, detail
// spoiler + ML link (Phase A, PR3).
// ---------------------------------------------------------------------------

const AWAITING_MESSAGE = {
  id: 10,
  ml_message_id: 'msg-await',
  pack_id: '2000013868175593',
  buyer_id: 173555877,
  buyer_nickname: 'JUAN_PEREZ',
  text: 'Buen día me pasas la factura',
  received_at: '2026-07-10T14:57:25Z',
  read_at: null,
  moderation_status: 'clean',
  bot_status: 'awaiting_human',
  drafted_answer: 'Claro, te la envío enseguida',
  intent_category: 'facturacion',
  confidence: 0.87,
};

const TAKEN_OVER_MESSAGE = { ...AWAITING_MESSAGE, id: 11, bot_status: 'taken_over' };

const CLAIM_MESSAGE = {
  ...AWAITING_MESSAGE,
  id: 12,
  bot_status: 'blocked_claim',
  drafted_answer: null,
};

function mockMessagesList(messages, { messagesSendEnabled = true } = {}) {
  api.get.mockImplementation((url) => {
    if (url === '/ml-bot/status') {
      return Promise.resolve({
        data: { bot_enabled: true, auto_publish_enabled: false, messages_send_enabled: messagesSendEnabled },
      });
    }
    if (url === '/ml-bot/questions') return Promise.resolve({ data: { questions: [] } });
    if (url === '/ml-bot/messages') return Promise.resolve({ data: { messages, total: messages.length } });
    return Promise.resolve({ data: {} });
  });
}

async function openMensajesTab(user) {
  const tabButton = await screen.findByRole('button', { name: /Mensajes/i });
  await user.click(tabButton);
}

describe('Mensajes tab — thread-header actions (permission-gated)', () => {
  it('does NOT render take-over/editar/enviar buttons for a read-only user (no ml_bot.messages.responder)', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'ml_bot.messages.responder');
    mockMessagesList([AWAITING_MESSAGE]);
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    await waitFor(() => {
      expect(screen.getByText(/JUAN_PEREZ/)).toBeInTheDocument();
    });

    expect(screen.queryByRole('button', { name: /tomar el mensaje/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^editar$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /enviar respuesta/i })).not.toBeInTheDocument();
  });

  it('renders "Tomar" for an awaiting_human anchor and calls take-over, then refetches', async () => {
    mockTienePermiso.mockImplementation(() => true);
    mockMessagesList([AWAITING_MESSAGE]);
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    const takeOverBtn = await screen.findByRole('button', { name: /tomar el mensaje/i });
    await user.click(takeOverBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(`/ml-bot/messages/${AWAITING_MESSAGE.id}/take-over`);
    });
    // Refetch after the action (mirrors Preguntas' runAction pattern).
    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/messages');
      expect(calls.length).toBeGreaterThan(1);
    });
  });

  it('renders "Tomar" for a failed anchor and calls take-over (finding 1: failed is recoverable, not a dead end)', async () => {
    mockTienePermiso.mockImplementation(() => true);
    const FAILED_MESSAGE = { ...AWAITING_MESSAGE, id: 13, bot_status: 'failed', last_error: 'ML rechazó el mensaje (400)' };
    mockMessagesList([FAILED_MESSAGE]);
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    const takeOverBtn = await screen.findByRole('button', { name: /tomar el mensaje/i });
    await user.click(takeOverBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(`/ml-bot/messages/${FAILED_MESSAGE.id}/take-over`);
    });
  });

  it('renders "Editar" + "Enviar" for a taken_over anchor; edit opens modal prefilled with drafted_answer, save calls PUT', async () => {
    mockTienePermiso.mockImplementation(() => true);
    mockMessagesList([TAKEN_OVER_MESSAGE]);
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    const editBtn = await screen.findByRole('button', { name: /^editar$/i });
    await user.click(editBtn);

    const textarea = await screen.findByDisplayValue(TAKEN_OVER_MESSAGE.drafted_answer);
    expect(textarea).toBeInTheDocument();

    fireEvent.change(textarea, { target: { value: 'Respuesta editada' } });
    await user.click(screen.getByRole('button', { name: /guardar borrador/i }));

    await waitFor(() => {
      expect(api.put).toHaveBeenCalledWith(
        `/ml-bot/messages/${TAKEN_OVER_MESSAGE.id}/answer`,
        { drafted_answer: 'Respuesta editada' }
      );
    });
  });

  it('calls the send endpoint when "Enviar" is clicked on a taken_over anchor', async () => {
    mockTienePermiso.mockImplementation(() => true);
    mockMessagesList([TAKEN_OVER_MESSAGE]);
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    const sendBtn = await screen.findByRole('button', { name: /enviar respuesta/i });
    await user.click(sendBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(`/ml-bot/messages/${TAKEN_OVER_MESSAGE.id}/send`);
    });
  });

  it('surfaces the TRANSIENT-retry message when sent: false and bot_status stays taken_over', async () => {
    mockTienePermiso.mockImplementation(() => true);
    mockMessagesList([TAKEN_OVER_MESSAGE]);
    api.post.mockImplementation((url) => {
      if (url === `/ml-bot/messages/${TAKEN_OVER_MESSAGE.id}/send`) {
        return Promise.resolve({ data: { message: TAKEN_OVER_MESSAGE, sent: false } });
      }
      return Promise.resolve({ data: {} });
    });
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    const sendBtn = await screen.findByRole('button', { name: /enviar respuesta/i });
    await user.click(sendBtn);

    // Exact transient wording — must NOT be confused with the permanent
    // "rechazado en forma permanente" message (finding 1: collapsing both
    // outcomes into one hardcoded string hid a dead-end thread).
    await waitFor(() => {
      expect(screen.getByText(/El envío no se completó \(falla transitoria\)\. El mensaje sigue disponible para reintentar\./i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/rechazado en forma permanente/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Enviado$/i)).not.toBeInTheDocument();
  });

  it('surfaces the PERMANENT-failure message with last_error when sent: false and bot_status is failed', async () => {
    mockTienePermiso.mockImplementation(() => true);
    mockMessagesList([TAKEN_OVER_MESSAGE]);
    const FAILED_MESSAGE = { ...TAKEN_OVER_MESSAGE, bot_status: 'failed', last_error: 'ML rechazó el mensaje (400)' };
    api.post.mockImplementation((url) => {
      if (url === `/ml-bot/messages/${TAKEN_OVER_MESSAGE.id}/send`) {
        return Promise.resolve({ data: { message: FAILED_MESSAGE, sent: false } });
      }
      return Promise.resolve({ data: {} });
    });
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    const sendBtn = await screen.findByRole('button', { name: /enviar respuesta/i });
    await user.click(sendBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/El envío fue rechazado en forma permanente: ML rechazó el mensaje \(400\)\. Podés retomar el mensaje para reintentar\./i),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/falla transitoria/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Enviado$/i)).not.toBeInTheDocument();
  });
});

describe('Mensajes tab — messages_send_enabled gate (visible to the UI)', () => {
  it('disables "Enviar" (with an explanatory title) when the gate is off, while Tomar/Editar stay enabled', async () => {
    mockTienePermiso.mockImplementation(() => true);
    mockMessagesList([TAKEN_OVER_MESSAGE], { messagesSendEnabled: false });
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    const sendBtn = await screen.findByRole('button', { name: /enviar respuesta/i });
    expect(sendBtn).toBeDisabled();
    expect(sendBtn).toHaveAttribute('title', expect.stringMatching(/deshabilitado/i));

    expect(screen.getByRole('button', { name: /^editar$/i })).toBeEnabled();
  });

  it('enables "Enviar" when the gate is on (existing send-endpoint test covers the click path)', async () => {
    mockTienePermiso.mockImplementation(() => true);
    mockMessagesList([TAKEN_OVER_MESSAGE], { messagesSendEnabled: true });
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    const sendBtn = await screen.findByRole('button', { name: /enviar respuesta/i });
    expect(sendBtn).toBeEnabled();
  });
});

describe('Mensajes tab — blocked_claim badge (no bot-send affordance)', () => {
  it('shows the claim badge and only a "Tomar" affordance, never Editar/Enviar, for blocked_claim', async () => {
    mockTienePermiso.mockImplementation(() => true);
    mockMessagesList([CLAIM_MESSAGE]);
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    await waitFor(() => {
      expect(screen.getByText(/Reclamo — el bot no responde/i)).toBeInTheDocument();
    });

    expect(screen.getByRole('button', { name: /tomar el mensaje/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^editar$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /enviar respuesta/i })).not.toBeInTheDocument();
  });
});

describe('Mensajes tab — detail spoiler (thread + draft + ML link)', () => {
  it('expands to show the full thread, the drafted answer, and a ML conversation link with the right href', async () => {
    mockTienePermiso.mockImplementation(() => true);
    mockMessagesList([AWAITING_MESSAGE]);
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    await waitFor(() => {
      expect(screen.getByText(/JUAN_PEREZ/)).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /ver detalle completo/i }));

    await waitFor(() => {
      expect(screen.getByText('Claro, te la envío enseguida')).toBeInTheDocument();
    });
    // Full conversation text renders (same message here, single-message thread).
    expect(screen.getAllByText(/Buen día me pasas la factura/).length).toBeGreaterThanOrEqual(1);

    const link = screen.getByRole('link', { name: /ver en mercadolibre/i });
    expect(link).toHaveAttribute(
      'href',
      `https://www.mercadolibre.com.ar/ventas/nueva/mensajeria/${AWAITING_MESSAGE.pack_id}`
    );
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });
});
