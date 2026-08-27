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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MLQuestions, { loadColumnSizing, saveColumnSizing, LLM_PROVIDER_MODELS } from './MLQuestions';
import api from '../services/api';

const COLUMN_SIZING_KEY = 'mlq:colsizing:preguntas';
const HISTORIAL_COLUMN_SIZING_KEY = 'mlq:colsizing:historial';
const MENSAJES_COLUMN_SIZING_KEY = 'mlq:colsizing:mensajes';
const PENDIENTES_COLUMN_SIZING_KEY = 'mlq:colsizing:pendientes';

/**
 * Deterministic clock for the Pendientes tab tests.
 *
 * MLQuestions mounts a live 1s ticker — `setInterval(() => setNow(Date.now()),
 * 1000)` — for relative-time display. Under REAL timers that interval fires a
 * `setNow` state update OUTSIDE React's `act()` while a `userEvent` interaction
 * (e.g. typing the 11-digit CUIT, ~1.2–3.6s of wall-clock) is mid-flush,
 * making the flush order non-deterministic: intermittently `handleConfirmDone`
 * early-returns on a stale `doneResolvedCuit` and never POSTs (~1-in-10 flake).
 *
 * Fake timers put every timer under vitest's control: the ticker only advances
 * when userEvent's wired `advanceTimers` advances it, and that advance is
 * `act()`-wrapped, so the race is gone. This is test-side determinism only —
 * the 1s interval is a real product feature and is NOT changed. The
 * conversion of the Pendientes list to a heavier TanStack table makes these
 * interactions longer, so the whole Pendientes suite runs on the fake clock.
 *
 * Call inside a `describe` block; it registers its own before/afterEach.
 */
function useDeterministicClock() {
  beforeEach(() => {
    // `shouldAdvanceTime: true` keeps a real-clock heartbeat so Testing
    // Library's `waitFor`/`findBy*` polling still fires; userEvent's wired
    // `advanceTimers` (below) drives the interaction timing in act()-wrapped
    // chunks. The pairing is what removes the un-act()'d `setNow` race — pure
    // fake timers (no heartbeat) instead hang `waitFor`.
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });
}

// userEvent wired to the fake clock — every internal delay advances vitest's
// timers (inside act), instead of waiting on real wall-clock.
const setupUserWithClock = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

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
    if (url === '/ml-bot/admin-pending') return Promise.resolve({ data: { requests: [], total: 0 } });
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

describe('Preguntas fallback_reason filter + counts (PR5)', () => {
  function mockQuestionsWithFallback({ counts = {}, rows = [], total } = {}) {
    api.get.mockImplementation((url) => {
      if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
      if (url === '/ml-bot/questions') {
        return Promise.resolve({ data: { questions: rows, total: total ?? rows.length } });
      }
      if (url === '/ml-bot/questions/fallback-reason-counts') {
        const total = Object.values(counts).reduce((a, b) => a + b, 0);
        return Promise.resolve({ data: { counts, total } });
      }
      if (url === '/ml-bot/messages') return Promise.resolve({ data: { messages: [], total: 0 } });
      if (url === '/ml-bot/admin-pending') return Promise.resolve({ data: { requests: [], total: 0 } });
      return Promise.resolve({ data: {} });
    });
  }

  it('sends fallback_reason and resets offset to 0 when the fallback-reason filter changes', async () => {
    mockQuestionsWithFallback({ total: 200 });
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-bot/questions', expect.anything());
    });

    // Advance to page 2 first, so we can prove the filter resets it back to 0.
    api.get.mockImplementation((url) => {
      if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
      if (url === '/ml-bot/questions') {
        return Promise.resolve({ data: { questions: [], total: 200 } });
      }
      if (url === '/ml-bot/questions/fallback-reason-counts') return Promise.resolve({ data: { counts: {}, total: 0 } });
      return Promise.resolve({ data: {} });
    });
    await user.click(screen.getByRole('button', { name: /siguiente/i }));
    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/questions');
      expect(calls[calls.length - 1][1].params.offset).toBe(50);
    });

    const reasonSelect = screen.getAllByRole('combobox')[1];
    await user.selectOptions(reasonSelect, 'low_confidence');

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/questions');
      const last = calls[calls.length - 1];
      expect(last[1].params).toEqual(
        expect.objectContaining({ offset: 0, fallback_reason: 'low_confidence' })
      );
    });
  });

  it('renders the per-reason count chips from GET /ml-bot/questions/fallback-reason-counts', async () => {
    mockQuestionsWithFallback({ counts: { low_confidence: 3, deflection: 1 } });

    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText('Confianza baja: 3')).toBeInTheDocument();
      expect(screen.getByText('Desvío: 1')).toBeInTheDocument();
    });
  });

  it('shows a fallback_reason badge on a row that has one, and no badge when it is null', async () => {
    mockQuestionsWithFallback({
      rows: [
        { id: 1, question_text: 'q1', status: 'failed', fallback_reason: 'low_confidence' },
        { id: 2, question_text: 'q2', status: 'failed', fallback_reason: null },
      ],
    });

    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText('q1')).toBeInTheDocument();
    });
    // "Confianza baja" also appears as a <select><option> label — assert the
    // rendered row badge specifically, not just any match on the text.
    const badges = screen.getAllByText('Confianza baja');
    expect(badges.some((el) => el.tagName !== 'OPTION')).toBe(true);
  });
});

describe('Preguntas pagination (PR1 — honest total, offset-based paging)', () => {
  function mockQuestionsPage({ total, offset }) {
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
      if (url === '/ml-bot/questions') {
        const requestedOffset = config?.params?.offset ?? 0;
        return Promise.resolve({
          data: {
            questions: requestedOffset === offset ? [{ id: 1, question_text: 'q', status: 'waiting' }] : [],
            total,
          },
        });
      }
      if (url === '/ml-bot/messages') return Promise.resolve({ data: { messages: [], total: 0 } });
      if (url === '/ml-bot/admin-pending') return Promise.resolve({ data: { requests: [], total: 0 } });
      return Promise.resolve({ data: {} });
    });
  }

  it('renders the honest total instead of silently truncating at the page size', async () => {
    mockQuestionsPage({ total: 1462, offset: 0 });

    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText(/1462/)).toBeInTheDocument();
    });
  });

  it('requests limit=50 and offset=0 on first load, never the old hardcoded limit=100', async () => {
    mockQuestionsPage({ total: 1462, offset: 0 });

    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/questions');
      expect(calls[calls.length - 1][1].params).toEqual(
        expect.objectContaining({ limit: 50, offset: 0 })
      );
    });
  });

  it('clicking "next" issues offset=50 and is reflected in the request', async () => {
    mockQuestionsPage({ total: 1462, offset: 0 });
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText(/1462/)).toBeInTheDocument();
    });

    mockQuestionsPage({ total: 1462, offset: 50 });
    const nextButton = screen.getByRole('button', { name: /siguiente/i });
    await user.click(nextButton);

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/questions');
      expect(calls[calls.length - 1][1].params).toEqual(
        expect.objectContaining({ limit: 50, offset: 50 })
      );
    });
  });

  it('disables "previous" on the first page and "next" on the last page', async () => {
    mockQuestionsPage({ total: 10, offset: 0 });
    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /anterior/i })).toBeDisabled();
      // total=10 fits in a single 50-row page: no more pages ahead either.
      expect(screen.getByRole('button', { name: /siguiente/i })).toBeDisabled();
    });
  });

  it('resets offset to 0 when the status filter changes', async () => {
    mockQuestionsPage({ total: 1462, offset: 0 });
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText(/1462/)).toBeInTheDocument();
    });

    mockQuestionsPage({ total: 1462, offset: 50 });
    await user.click(screen.getByRole('button', { name: /siguiente/i }));
    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/questions');
      expect(calls[calls.length - 1][1].params.offset).toBe(50);
    });

    mockQuestionsPage({ total: 5, offset: 0 });
    const statusSelect = screen.getAllByRole('combobox')[0];
    await user.selectOptions(statusSelect, 'failed');

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/questions');
      const last = calls[calls.length - 1];
      expect(last[1].params).toEqual(
        expect.objectContaining({ offset: 0, status: 'failed' })
      );
    });
  });
});

describe('Preguntas — publish-now feedback (PR2, ADR-2: backend wrapper + runAction fix)', () => {
  const PUBLISHABLE_QUESTION = {
    id: 7,
    question_text: '¿Tiene stock?',
    status: 'taken_over',
    drafted_answer: 'Sí, tenemos stock.',
  };

  function mockQuestionsList(question) {
    api.get.mockImplementation((url) => {
      if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
      if (url === '/ml-bot/questions') return Promise.resolve({ data: { questions: [question], total: 1 } });
      if (url === '/ml-bot/messages') return Promise.resolve({ data: { messages: [], total: 0 } });
      if (url === '/ml-bot/admin-pending') return Promise.resolve({ data: { requests: [], total: 0 } });
      return Promise.resolve({ data: {} });
    });
  }

  it('shows no error when the wrapped response reports published: true', async () => {
    const user = userEvent.setup();
    mockQuestionsList(PUBLISHABLE_QUESTION);
    api.post.mockResolvedValue({
      data: {
        question: { ...PUBLISHABLE_QUESTION, status: 'published' },
        published: true,
        outcome: 'published',
      },
    });

    await renderWithRouter(<MLQuestions />);
    await user.click(await screen.findByLabelText('Publicar ahora'));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/ml-bot/questions/7/publish-now');
    });
    expect(screen.queryByText(/no se pudo completar/i)).not.toBeInTheDocument();
  });

  it('surfaces last_error when the outcome is a permanent failure', async () => {
    const user = userEvent.setup();
    mockQuestionsList(PUBLISHABLE_QUESTION);
    api.post.mockResolvedValue({
      data: {
        question: { ...PUBLISHABLE_QUESTION, status: 'failed', last_error: 'ML rechazó la respuesta (422)' },
        published: false,
        outcome: 'failed',
      },
    });

    await renderWithRouter(<MLQuestions />);
    await user.click(await screen.findByLabelText('Publicar ahora'));

    expect(await screen.findByText(/ML rechazó la respuesta \(422\)/)).toBeInTheDocument();
  });

  it('surfaces a transient-failure message when the outcome is retry', async () => {
    const user = userEvent.setup();
    mockQuestionsList(PUBLISHABLE_QUESTION);
    api.post.mockResolvedValue({
      data: {
        question: { ...PUBLISHABLE_QUESTION, status: 'waiting' },
        published: false,
        outcome: 'retry',
      },
    });

    await renderWithRouter(<MLQuestions />);
    await user.click(await screen.findByLabelText('Publicar ahora'));

    expect(await screen.findByText(/falla transitoria/i)).toBeInTheDocument();
  });

  it('falls back to err.message when the thrown error carries no response body (regression: runAction lacked this fallback)', async () => {
    const user = userEvent.setup();
    mockQuestionsList(PUBLISHABLE_QUESTION);
    api.post.mockRejectedValue(new Error('Network Error'));

    await renderWithRouter(<MLQuestions />);
    await user.click(await screen.findByLabelText('Publicar ahora'));

    expect(await screen.findByText('Network Error')).toBeInTheDocument();
  });
});

describe('Preguntas — send visibility & failure legibility (PR3)', () => {
  function mockQuestionsList(question) {
    api.get.mockImplementation((url) => {
      if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
      if (url === '/ml-bot/questions') return Promise.resolve({ data: { questions: [question], total: 1 } });
      if (url === '/ml-bot/messages') return Promise.resolve({ data: { messages: [], total: 0 } });
      if (url === '/ml-bot/admin-pending') return Promise.resolve({ data: { requests: [], total: 0 } });
      return Promise.resolve({ data: {} });
    });
  }

  it('renders the question arrival date column (the table had none before)', async () => {
    mockQuestionsList({
      id: 1,
      question_text: '¿Hay stock?',
      status: 'waiting',
      question_date: '2026-08-20T10:00:00Z',
    });

    await renderWithRouter(<MLQuestions />);

    expect(await screen.findByText('Fecha')).toBeInTheDocument();
    expect(await screen.findByText(new Date('2026-08-20T10:00:00Z').toLocaleString())).toBeInTheDocument();
  });

  it('surfaces published_at on a published row', async () => {
    mockQuestionsList({
      id: 2,
      question_text: '¿Envían a domicilio?',
      status: 'published',
      question_date: '2026-08-20T10:00:00Z',
      published_at: '2026-08-20T10:05:00Z',
    });

    await renderWithRouter(<MLQuestions />);

    expect(await screen.findByText(
      `Publicada: ${new Date('2026-08-20T10:05:00Z').toLocaleString()}`
    )).toBeInTheDocument();
  });

  it('shows a placeholder instead of nothing when a published row has no published_at', async () => {
    mockQuestionsList({
      id: 3,
      question_text: '¿Tiene garantía?',
      status: 'published',
      question_date: '2026-08-20T10:00:00Z',
      published_at: null,
    });

    await renderWithRouter(<MLQuestions />);

    expect(await screen.findByText('Publicada (fecha desconocida)')).toBeInTheDocument();
  });

  it('surfaces attempts and last_error only on failed rows', async () => {
    mockQuestionsList({
      id: 4,
      question_text: '¿Es original?',
      status: 'failed',
      question_date: '2026-08-20T10:00:00Z',
      attempts: 2,
      last_error: 'ML rechazó la respuesta (422)',
    });

    await renderWithRouter(<MLQuestions />);

    expect(await screen.findByText(/Intentos: 2 — ML rechazó la respuesta \(422\)/)).toBeInTheDocument();
  });

  it('does not render attempts/last_error on a non-failed row', async () => {
    mockQuestionsList({
      id: 5,
      question_text: '¿Cuánto tarda el envío?',
      status: 'waiting',
      question_date: '2026-08-20T10:00:00Z',
      attempts: 0,
      last_error: null,
    });

    await renderWithRouter(<MLQuestions />);

    await screen.findByText('¿Cuánto tarda el envío?');
    expect(screen.queryByText(/Intentos:/)).not.toBeInTheDocument();
  });

  it('keeps the empty/loading row colSpan in sync with the new column count (Preguntas)', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
      if (url === '/ml-bot/questions') return Promise.resolve({ data: { questions: [], total: 0 } });
      if (url === '/ml-bot/messages') return Promise.resolve({ data: { messages: [], total: 0 } });
      if (url === '/ml-bot/admin-pending') return Promise.resolve({ data: { requests: [], total: 0 } });
      return Promise.resolve({ data: {} });
    });

    await renderWithRouter(<MLQuestions />);

    const emptyCell = await screen.findByText('No hay preguntas para mostrar');
    expect(emptyCell.closest('td').getAttribute('colspan')).toBe('8');
  });
});

describe('Mensajes pagination (PR1 — honest total, offset-based paging)', () => {
  function mockMessagesPage({ total, offset }) {
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
      if (url === '/ml-bot/questions') return Promise.resolve({ data: { questions: [] } });
      if (url === '/ml-bot/messages') {
        const requestedOffset = config?.params?.offset ?? 0;
        return Promise.resolve({
          // A page beyond the one this call configured returns an empty
          // page — the real server behavior for an out-of-range offset —
          // so a test asserting on `offset` actually exercises the request
          // parameter instead of a constant mock response.
          data: { messages: [], total: requestedOffset === offset ? total : 0 },
        });
      }
      if (url === '/ml-bot/admin-pending') return Promise.resolve({ data: { requests: [], total: 0 } });
      return Promise.resolve({ data: {} });
    });
  }

  it('requests limit=50 and offset=0 and renders the honest total', async () => {
    mockMessagesPage({ total: 730, offset: 0 });
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    const tabButton = await screen.findByRole('button', { name: /Mensajes/i });
    await user.click(tabButton);

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/messages');
      expect(calls[calls.length - 1][1].params).toEqual(
        expect.objectContaining({ limit: 50, offset: 0 })
      );
      expect(screen.getByText(/730/)).toBeInTheDocument();
    });
  });

  it('resets offset to 0 when the buyer filter changes', async () => {
    mockMessagesPage({ total: 730, offset: 0 });
    const user = userEvent.setup();
    await renderWithRouter(<MLQuestions />);

    const tabButton = await screen.findByRole('button', { name: /Mensajes/i });
    await user.click(tabButton);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-bot/messages', expect.anything());
    });

    const nextButton = screen.getAllByRole('button', { name: /siguiente/i })[0];
    await user.click(nextButton);

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/messages');
      expect(calls[calls.length - 1][1].params.offset).toBe(50);
    });

    const buyerInput = screen.getByPlaceholderText(/comprador/i);
    await user.type(buyerInput, '1');

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/messages');
      const last = calls[calls.length - 1];
      expect(last[1].params.offset).toBe(0);
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
    expect(cols.length).toBe(8);

    // Resizable: Pregunta, Item, Respuesta (borrador). Fixed: Fecha, Estado,
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

describe('Mensajes tab — send the bot draft without opening the detail', () => {
  it('shows the bot draft inline on the collapsed thread row', async () => {
    const user = userEvent.setup();
    mockMessagesList([AWAITING_MESSAGE]);

    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    // No expand, no modal: the draft is readable straight from the row.
    expect(await screen.findByText('Claro, te la envío enseguida')).toBeInTheDocument();
  });

  it('offers a direct send from awaiting_human and POSTs to /send', async () => {
    const user = userEvent.setup();
    mockMessagesList([AWAITING_MESSAGE]);
    api.post.mockResolvedValue({ data: { sent: true, message: { ...AWAITING_MESSAGE, bot_status: 'sent' } } });

    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    const sendButton = await screen.findByLabelText('Enviar la respuesta del bot');
    await user.click(sendButton);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/ml-bot/messages/10/send');
    });
  });

  it('does not offer a direct send when there is no draft to send', async () => {
    const user = userEvent.setup();
    mockMessagesList([{ ...AWAITING_MESSAGE, drafted_answer: null }]);

    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    await screen.findByText(/JUAN_PEREZ/);
    expect(screen.queryByLabelText('Enviar la respuesta del bot')).not.toBeInTheDocument();
  });

  it('disables the direct send while messages_send_enabled is off', async () => {
    const user = userEvent.setup();
    mockMessagesList([AWAITING_MESSAGE], { messagesSendEnabled: false });

    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    expect(await screen.findByLabelText('Enviar la respuesta del bot')).toBeDisabled();
  });

  it('never offers a direct send on a claim', async () => {
    const user = userEvent.setup();
    mockMessagesList([{ ...CLAIM_MESSAGE, drafted_answer: 'no debería enviarse' }]);

    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    await screen.findByText(/JUAN_PEREZ/);
    expect(screen.queryByLabelText('Enviar la respuesta del bot')).not.toBeInTheDocument();
  });

  it('shows what the buyer bought and where the shipment is, in one batched call', async () => {
    const user = userEvent.setup();
    mockMessagesList([AWAITING_MESSAGE]);
    const base = api.get.getMockImplementation();
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-bot/messages/order-context') {
        return Promise.resolve({
          data: {
            contexts: {
              [AWAITING_MESSAGE.pack_id]: {
                items: [{ title: 'Router TP-Link AX55', quantity: 2 }],
                order_status: 'paid',
                shipping: { status: 'shipped', substatus: 'in_transit' },
              },
            },
          },
        });
      }
      return base(url, config);
    });

    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    expect(await screen.findByText(/Router TP-Link AX55/)).toBeInTheDocument();
    expect(screen.getByText(/envío: shipped \/ in_transit/)).toBeInTheDocument();

    // One batched request for the whole list, not one per thread.
    const ctxCalls = api.get.mock.calls.filter((c) => c[0] === '/ml-bot/messages/order-context');
    expect(ctxCalls).toHaveLength(1);
    expect(ctxCalls[0][1].params.pack_ids).toBe(AWAITING_MESSAGE.pack_id);
  });

  it('renders the thread normally when the order context call fails', async () => {
    const user = userEvent.setup();
    mockMessagesList([AWAITING_MESSAGE]);
    const base = api.get.getMockImplementation();
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-bot/messages/order-context') return Promise.reject(new Error('boom'));
      return base(url, config);
    });

    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    // Decision context is best-effort — losing it must never hide the message.
    expect(await screen.findByText('Claro, te la envío enseguida')).toBeInTheDocument();
  });

  it('shows a row being sent as such and offers no action on it', async () => {
    // A send in flight must not be actionable: taking it over would hand the
    // operator the untouched draft with the send button live, on a message the
    // buyer may already have received. The state is still labelled so it is
    // visible rather than a bare status string.
    const user = userEvent.setup();
    mockMessagesList([{ ...AWAITING_MESSAGE, bot_status: 'sending' }]);

    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    expect(await screen.findByText('Enviando…')).toBeInTheDocument();
    expect(screen.queryByLabelText('Tomar el mensaje')).not.toBeInTheDocument();
  });

  it('never offers a direct send on a row already being sent', async () => {
    const user = userEvent.setup();
    mockMessagesList([{ ...AWAITING_MESSAGE, bot_status: 'sending' }]);

    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    await screen.findByText(/JUAN_PEREZ/);
    expect(screen.queryByLabelText('Enviar la respuesta del bot')).not.toBeInTheDocument();
  });

  it('never lets a stale order-context response overwrite a newer one', async () => {
    // The fetch is intentionally un-awaited so the list is not gated on it.
    // That opens a window: the SSE channel refetches, and a slow earlier
    // response could land after a newer one and show stale purchases.
    const user = userEvent.setup();
    mockMessagesList([AWAITING_MESSAGE]);
    const base = api.get.getMockImplementation();

    let call = 0;
    const resolvers = [];
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-bot/messages/order-context') {
        call += 1;
        const title = call === 1 ? 'VIEJO stale' : 'NUEVO fresco';
        return new Promise((resolve) => {
          resolvers.push(() =>
            resolve({
              data: { contexts: { [AWAITING_MESSAGE.pack_id]: { items: [{ title, quantity: 1 }] } } },
            })
          );
        });
      }
      return base(url, config);
    });

    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);
    await waitFor(() => expect(resolvers).toHaveLength(1));

    // Force a second load (changing a filter refetches the list), then
    // resolve them out of order: newest first, stale last. The stale one must
    // be discarded.
    await user.click(screen.getByLabelText(/incluir moderados/i));
    await waitFor(() => expect(resolvers).toHaveLength(2));

    resolvers[1]();
    await waitFor(() => expect(screen.getByText(/NUEVO fresco/)).toBeInTheDocument());

    resolvers[0]();
    await waitFor(() => expect(screen.getByText(/NUEVO fresco/)).toBeInTheDocument());
    expect(screen.queryByText(/VIEJO stale/)).not.toBeInTheDocument();
  });

  it('labels who wrote the answer — bot vs fallback', async () => {
    const user = userEvent.setup();
    mockMessagesList([{ ...AWAITING_MESSAGE, answer_source: 'fallback' }]);

    await renderWithRouter(<MLQuestions />);
    await openMensajesTab(user);

    expect(await screen.findByText('fallback')).toBeInTheDocument();
  });
});

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

/**
 * Phase 6 (PR3) — "Pendientes" tab (ml-bot-admin-pending).
 * Scope: tab visibility gated by `ml_bot.admin_pending.ver`; filtered list
 * with columns/badges; detail/prefill view (extracted vs AFIP); done modal
 * blocking submit without `resolved_cuit`.
 */

const PENDING_ROW = {
  id: 1,
  pack_id: '2000013868175593',
  buyer_id: 173555877,
  source: 'bot_derived',
  status: 'new',
  extracted_cuit: '20147683511',
  extracted_name: 'Luis Eck',
  cuit_valid: false,
  doc_mismatch: true,
  afip_status: 'ok',
  created_at: '2026-07-20T10:00:00Z',
  message_id: 55,
};

function mockPendingList(requests) {
  api.get.mockImplementation((url) => {
    if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
    if (url === '/ml-bot/questions') return Promise.resolve({ data: { questions: [] } });
    if (url === '/ml-bot/messages') return Promise.resolve({ data: { messages: [] } });
    if (url === '/ml-bot/admin-pending') return Promise.resolve({ data: { requests, total: requests.length } });
    return Promise.resolve({ data: {} });
  });
}

describe('Pendientes tab visibility', () => {
  useDeterministicClock();

  it('test_pendientes_tab_renders_filtered_list — shows columns/badges under ml_bot.admin_pending.ver', async () => {
    mockTienePermiso.mockImplementation(() => true);
    mockPendingList([PENDING_ROW]);

    const user = setupUserWithClock();
    await renderWithRouter(<MLQuestions />);

    const tabButton = await screen.findByRole('button', { name: /Pendientes/i });
    await user.click(tabButton);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-bot/admin-pending', expect.anything());
    });

    await waitFor(() => {
      expect(screen.getByText('20147683511')).toBeInTheDocument();
    });
    expect(screen.getByText('Luis Eck')).toBeInTheDocument();
    expect(screen.getAllByText('CUIT inválido').length).toBeGreaterThanOrEqual(1);
    // The doc-mismatch badge was removed: it fired on every company CUIT.
    expect(screen.queryByText('Discrepancia doc.')).not.toBeInTheDocument();
    expect(screen.getAllByText('Nuevo').length).toBeGreaterThanOrEqual(1);
  });

  it('hides the "Pendientes" tab and panel when ml_bot.admin_pending.ver is not granted', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'ml_bot.admin_pending.ver');
    mockPendingList([PENDING_ROW]);

    await renderWithRouter(<MLQuestions />);

    await waitFor(() => {
      expect(screen.getByText('Preguntas')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /Pendientes/i })).not.toBeInTheDocument();
    expect(screen.queryByText('20147683511')).not.toBeInTheDocument();
  });
});

describe('Pendientes detail — extracted vs AFIP prefill', () => {
  useDeterministicClock();

  it('test_detail_prefill_view_shows_extracted_vs_afip — renders side-by-side extracted and AFIP/stored data', async () => {
    mockTienePermiso.mockImplementation(() => true);
    api.get.mockImplementation((url) => {
      if (url === '/ml-bot/status') return Promise.resolve({ data: { bot_enabled: true, auto_publish_enabled: false } });
      if (url === '/ml-bot/questions') return Promise.resolve({ data: { questions: [] } });
      if (url === '/ml-bot/messages') return Promise.resolve({ data: { messages: [] } });
      if (url === '/ml-bot/admin-pending') return Promise.resolve({ data: { requests: [PENDING_ROW], total: 1 } });
      if (url === '/ml-bot/admin-pending/1') {
        return Promise.resolve({
          data: {
            id: 1,
            extracted_cuit: '20147683511',
            extracted_name: 'Luis Eck',
            raw_text: 'Factura A por favor',
            afip_razon_social: 'LUIS AUGUSTO ECK',
            afip_condicion_iva: 'Responsable Inscripto',
            afip_domicilio: 'Calle Falsa 123',
            superseded_values: [],
            suggested_ack_template: 'Se realizará el cambio a la brevedad',
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const user = setupUserWithClock();
    await renderWithRouter(<MLQuestions />);
    const tabButton = await screen.findByRole('button', { name: /Pendientes/i });
    await user.click(tabButton);

    const detailToggle = await screen.findByRole('button', { name: /ver detalle/i });
    await user.click(detailToggle);

    await waitFor(() => {
      expect(screen.getByText(/Extraído \(mensaje del comprador\)/i)).toBeInTheDocument();
      expect(screen.getByText(/AFIP \/ almacenado/i)).toBeInTheDocument();
      expect(screen.getByText(/LUIS AUGUSTO ECK/)).toBeInTheDocument();
      expect(screen.getByText(/Se realizará el cambio a la brevedad/)).toBeInTheDocument();
    });

    // Ack hand-off jumps to the existing Mensajes take-over/edit/send flow,
    // with the template prefilled as the draft — nothing sends automatically.
    await user.click(screen.getByRole('button', { name: /Preparar acuse/i }));
    await waitFor(() => {
      expect(screen.getByText(/Editar respuesta — mensaje #55/i)).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue('Se realizará el cambio a la brevedad')).toBeInTheDocument();
  });
});

describe('Pendientes — done modal captures resolved_cuit', () => {
  useDeterministicClock();

  it('test_done_modal_captures_resolved_cuit — blocks submit until resolved_cuit is filled', async () => {
    mockTienePermiso.mockImplementation(() => true);
    mockPendingList([{ ...PENDING_ROW, id: 7, status: 'in_progress', extracted_cuit: '', cuit_valid: null, doc_mismatch: false }]);

    const user = setupUserWithClock();
    await renderWithRouter(<MLQuestions />);
    const tabButton = await screen.findByRole('button', { name: /Pendientes/i });
    await user.click(tabButton);

    const resolverButton = await screen.findByRole('button', { name: /Resolver/i });
    await user.click(resolverButton);

    const confirmButton = await screen.findByRole('button', { name: /Confirmar resolución/i });
    expect(confirmButton).toBeDisabled();

    const cuitInput = screen.getByPlaceholderText('20147683511');
    await user.type(cuitInput, '20147683511');
    expect(confirmButton).not.toBeDisabled();

    await user.click(confirmButton);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/ml-bot/admin-pending/7/done', { resolved_cuit: '20147683511' });
    });
  });
});

describe('Pendientes table — column-sizing persistence (loadColumnSizing/saveColumnSizing)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns {} when the key is absent', () => {
    expect(loadColumnSizing(PENDIENTES_COLUMN_SIZING_KEY)).toEqual({});
  });

  it('returns {} (never throws) when the stored value is corrupt JSON', () => {
    localStorage.setItem(PENDIENTES_COLUMN_SIZING_KEY, '{not valid json');
    expect(() => loadColumnSizing(PENDIENTES_COLUMN_SIZING_KEY)).not.toThrow();
    expect(loadColumnSizing(PENDIENTES_COLUMN_SIZING_KEY)).toEqual({});
  });

  it('round-trips a valid columnSizing object under its own key', () => {
    const sizing = { packComprador: 220, cuit: 160 };
    saveColumnSizing(sizing, PENDIENTES_COLUMN_SIZING_KEY);
    expect(loadColumnSizing(PENDIENTES_COLUMN_SIZING_KEY)).toEqual(sizing);
  });

  it('does not collide with the Mensajes/Preguntas/Historial keys', () => {
    saveColumnSizing({ packComprador: 300 }, PENDIENTES_COLUMN_SIZING_KEY);
    expect(loadColumnSizing(COLUMN_SIZING_KEY)).toEqual({});
    expect(loadColumnSizing(MENSAJES_COLUMN_SIZING_KEY)).toEqual({});
    expect(loadColumnSizing(HISTORIAL_COLUMN_SIZING_KEY)).toEqual({});
  });
});

describe('Pendientes table — TanStack column-sizing render structure', () => {
  useDeterministicClock();

  it('renders one <col> per header and resize grips only on the three text columns', async () => {
    localStorage.clear();
    mockPendingList([PENDING_ROW]);
    const user = setupUserWithClock();
    await renderWithRouter(<MLQuestions />);

    const tabButton = await screen.findByRole('button', { name: /Pendientes/i });
    await user.click(tabButton);

    await waitFor(() => {
      expect(screen.getByText('Pack / Comprador')).toBeInTheDocument();
    });

    const table = screen.getByText('Pack / Comprador').closest('table');
    const cols = table.querySelectorAll('colgroup > col');
    const headers = table.querySelectorAll('thead th');
    expect(cols.length).toBe(headers.length);
    expect(cols.length).toBe(9);

    // Resizable: Pack / Comprador, CUIT extraído, Nombre extraído. Fixed:
    // Origen, Estado, Alertas, AFIP, Creado, Acciones.
    const grips = table.querySelectorAll('thead [role="separator"]');
    expect(grips.length).toBe(3);

    // The detail row spans the full colgroup (colSpan === leaf column count).
    const detailToggle = table.querySelector('[aria-label="Ver detalle"]');
    expect(detailToggle).not.toBeNull();
  });

  it('shows the reset-columns control only once sizing has been customized', async () => {
    localStorage.clear();
    mockPendingList([PENDING_ROW]);
    const user = setupUserWithClock();
    await renderWithRouter(<MLQuestions />);

    const tabButton = await screen.findByRole('button', { name: /Pendientes/i });
    await user.click(tabButton);

    await waitFor(() => {
      expect(screen.getByText('Pack / Comprador')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /restablecer columnas/i })).not.toBeInTheDocument();
  });

  it('mounts with a previously persisted custom width and shows the reset control', async () => {
    localStorage.setItem(PENDIENTES_COLUMN_SIZING_KEY, JSON.stringify({ packComprador: 260 }));
    mockPendingList([PENDING_ROW]);
    const user = setupUserWithClock();
    await renderWithRouter(<MLQuestions />);

    const tabButton = await screen.findByRole('button', { name: /Pendientes/i });
    await user.click(tabButton);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /restablecer columnas/i })).toBeInTheDocument();
    });
    localStorage.clear();
  });
});

// ---------------------------------------------------------------------------
// LLM roster editor — the curated model dropdown must not offer model ids the
// provider rejects. An unknown id answers 4xx, which the backend treats as a
// permanent error (no retry), so the provider silently drops out of the
// rotation. PR #1004 fixed the backend defaults and the stored roster; this
// list is the remaining door into the same bug.
// ---------------------------------------------------------------------------

const RETIRED_MODEL_IDS = [
  'llama-3.3-70b',
  'llama3.1-8b',
  'meta-llama/llama-3.3-70b-instruct:free',
];

describe('LLM_PROVIDER_MODELS curated dropdown', () => {
  it('offers no model id that its provider no longer serves', () => {
    const offered = Object.values(LLM_PROVIDER_MODELS).flat();
    const stillOffered = RETIRED_MODEL_IDS.filter((id) => offered.includes(id));
    expect(stillOffered).toEqual([]);
  });

  it('lists the backend default first for every provider', () => {
    // MLQuestions adds a new roster entry with LLM_PROVIDER_MODELS[name][0],
    // so the first element is what an operator gets without choosing. It must
    // match provider_rotation._known_provider_specs on the backend.
    expect(LLM_PROVIDER_MODELS.groq[0]).toBe('llama-3.3-70b-versatile');
    expect(LLM_PROVIDER_MODELS.cerebras[0]).toBe('gpt-oss-120b');
    expect(LLM_PROVIDER_MODELS.openrouter[0]).toBe('openai/gpt-oss-20b:free');
  });

  it('covers every provider the backend knows about', () => {
    expect(Object.keys(LLM_PROVIDER_MODELS).sort()).toEqual(['cerebras', 'groq', 'openrouter']);
  });
});

describe('LLM roster editor — a stored model outside the curated list', () => {
  function mockConfigWithRoster(rosterJson) {
    const base = api.get.getMockImplementation();
    api.get.mockImplementation((url, config) => {
      if (url === '/ml-bot/config') {
        return Promise.resolve({
          data: { items: [{ clave: 'llm_providers', valor: rosterJson, tipo: 'string', descripcion: '' }] },
        });
      }
      if (url === '/ml-bot/examples') return Promise.resolve({ data: { examples: [] } });
      return base(url, config);
    });
  }

  it('keeps a retired model visible as custom instead of dropping it silently', async () => {
    // A roster saved before the model ids were corrected still holds the old
    // value. The operator must be able to SEE what is configured — otherwise
    // the panel shows a plausible-looking dropdown that hides the real setting.
    const user = userEvent.setup();
    mockConfigWithRoster('[{"name":"cerebras","model":"llama-3.3-70b","enabled":true}]');

    await renderWithRouter(<MLQuestions />);
    await user.click(await screen.findByRole('button', { name: /Configuración/i }));

    expect(await screen.findByDisplayValue('llama-3.3-70b')).toBeInTheDocument();
  });
});
