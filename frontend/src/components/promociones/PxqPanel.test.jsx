import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PxqPanel from './PxqPanel';
import { pxqAPI } from '../../services/api';

// setup.js stubs PermisosContext globally with tienePermiso() => true, so the
// read gate is invisible unless this test overrides it locally.
const { mockTienePermiso } = vi.hoisted(() => ({ mockTienePermiso: vi.fn(() => true) }));
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: mockTienePermiso, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

// READ THIS BEFORE ASSERTING ON AN ERROR PAYLOAD HERE.
//
// This replaces the WHOLE `services/api` module, so the axios response
// interceptor in it NEVER RUNS in this file. Every `detail` below is handed to
// the component by hand. That is fine for testing what the component does with
// a payload — but it proves NOTHING about the payload the component actually
// receives in production, and it is exactly how the `adopt_conflict` and
// `divergence` branches shipped dead: the interceptor was flattening every
// object `detail` to a string, and no test here could see it.
//
// The shape of an error payload — flattened, passed through, or lifted out of
// the response root — is covered in `src/services/api.pxq.test.js`, which
// unmocks this module and drives the real interceptor. Assertions about SHAPE
// belong there; assertions about what the component RENDERS belong here.
vi.mock('../../services/api', () => ({
  pxqAPI: {
    getLive: vi.fn(),
    createTier: vi.fn(),
    updateTier: vi.fn(),
    deleteTier: vi.fn(),
    sync: vi.fn(),
    adoptLive: vi.fn(),
  },
}));

function renderPanel(props = {}) {
  const pxqCacheRef = { current: new Map() };
  return render(<PxqPanel itemId="MLA001" pxqCacheRef={pxqCacheRef} {...props} />);
}

describe('PxqPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
  });

  afterEach(() => {
    mockTienePermiso.mockReturnValue(true);
  });

  it('shows nothing at all without pxq.ver — never renders an error/403 for a view-only-denied user', async () => {
    mockTienePermiso.mockReturnValue(false);
    const { container } = renderPanel();
    expect(container).toBeEmptyDOMElement();
    expect(pxqAPI.getLive).not.toHaveBeenCalled();
  });

  it('shows a loading state while the live-state fetch is in flight', async () => {
    let resolveFetch;
    pxqAPI.getLive.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );

    renderPanel();
    expect(screen.getByText(/cargando precios mayoristas/i)).toBeInTheDocument();

    resolveFetch({
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [],
        mirror_tiers: [],
        fetched_at: '2026-08-01T10:00:00Z',
      },
    });
    await waitFor(() => expect(screen.queryByText(/cargando precios mayoristas/i)).not.toBeInTheDocument());
  });

  it('shows an error band with retry when the request itself fails', async () => {
    pxqAPI.getLive.mockRejectedValueOnce(new Error('network'));
    renderPanel();

    await waitFor(() => expect(screen.getByText(/error al cargar precios mayoristas/i)).toBeInTheDocument());

    pxqAPI.getLive.mockResolvedValueOnce({
      data: { item_id: 'MLA001', live_status: 'ok', live_tiers: [], mirror_tiers: [], fetched_at: '2026-08-01T10:00:00Z' },
    });
    screen.getByRole('button', { name: /reintentar/i }).click();
    await waitFor(() => expect(screen.queryByText(/error al cargar precios mayoristas/i)).not.toBeInTheDocument());
  });

  it('shows plainly that live state is unavailable (never "0 tramos en vivo") while still showing the mirror', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        live_status: 'unavailable',
        live_tiers: null,
        mirror_tiers: [
          { id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' },
        ],
        fetched_at: '2026-08-01T10:00:00Z',
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText(/no se pudo leer el estado en vivo/i)).toBeInTheDocument());
    expect(screen.queryByText(/0 tramos en vivo/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/5/).length).toBeGreaterThan(0);
  });

  it('shows the empty state distinctly when ML really has no tiers ([] not null)', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [],
        mirror_tiers: [],
        fetched_at: '2026-08-01T10:00:00Z',
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText(/ml no tiene tramos mayoristas/i)).toBeInTheDocument());
  });

  it('renders live and mirror tiers side by side when both are present', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 100 }],
        mirror_tiers: [
          { id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: 'PXQ1', estado: 'sincronizado' },
        ],
        fetched_at: '2026-08-01T10:00:00Z',
      },
    });

    renderPanel();

    // Matched on the full column heading, not a bare /en mercadolibre/: the
    // write button below now reads "Actualizar precios en MercadoLibre", so the
    // loose matcher would resolve to two nodes and throw.
    await waitFor(() => expect(screen.getByText(/en mercadolibre \(en vivo\)/i)).toBeInTheDocument());
    expect(screen.getByText(/mirror local/i)).toBeInTheDocument();
  });

  it('marks a divergent tier visibly (no resolution action offered — read only)', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 150 }],
        mirror_tiers: [
          { id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: 'PXQ1', estado: 'sincronizado' },
        ],
        fetched_at: '2026-08-01T10:00:00Z',
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText(/diverge/i)).toBeInTheDocument());
    // The price-update action existing elsewhere in the panel is fine (PR 4d) —
    // what this read-only comparison must never offer is an inline
    // "resolver"/auto-fix action right next to the divergent row itself.
    expect(screen.queryByRole('button', { name: /^resolver$/i })).not.toBeInTheDocument();
  });
});

// `estado` is a persisted domain value pinned by `ck_ml_pxq_tier_estado_valido`
// (`backend/app/models/ml_pxq_tier.py`), so the MOCKS below keep sending the raw
// backend values — that is the real payload, not copy. What is asserted is what
// the operator READS, which is now a presented label instead of the bare enum.
describe('PxqPanel — mirror estado is presented, not echoed', () => {
  function mockOneTier(estado) {
    return {
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [],
        mirror_tiers: [
          { id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado },
        ],
        fetched_at: '2026-08-01T10:00:00Z',
      },
    };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
  });

  // The four members of `ESTADOS_VALIDOS`, each proved to reach the operator as
  // a label AND proved not to leak the identifier that produced it.
  it.each([
    ['incompleto', 'Incompleto'],
    ['listo', 'Listo'],
    ['sincronizado', 'Actualizado en MercadoLibre'],
    ['desconocido', 'Desconocido'],
  ])('renders estado %s as "%s"', async (estado, label) => {
    pxqAPI.getLive.mockResolvedValue(mockOneTier(estado));
    renderPanel();

    expect(await screen.findByText(label)).toBeInTheDocument();
    // Exact-match query: without the anchors, "Incompleto" would also match the
    // authoring form's "Incompleto: falta el costo de envío del bulto" badge.
    expect(screen.queryByText(new RegExp(`^${estado}$`))).not.toBeInTheDocument();
  });

  // The map must never be the reason a cell goes blank. The backend can grow a
  // fifth `estado` (a CHECK-constraint edit, no frontend deploy) and the panel
  // has to keep telling the operator what the row actually says.
  it('falls back to the raw value for an estado the map does not know', async () => {
    pxqAPI.getLive.mockResolvedValue(mockOneTier('pendiente_revision'));
    renderPanel();

    expect(await screen.findByText('pendiente_revision')).toBeInTheDocument();
  });

  // Inherited keys are not entries. With a plain object literal this would hand
  // `Object.prototype.toString` — a FUNCTION — to React and blow up the render.
  it('does not resolve inherited object keys as labels', async () => {
    pxqAPI.getLive.mockResolvedValue(mockOneTier('toString'));
    renderPanel();

    expect(await screen.findByText('toString')).toBeInTheDocument();
  });

  // THE guardrail for the whole rename. The button stopped saying "sincronizar"
  // first; this row kept saying "sincronizado" to the operator afterwards,
  // because a domain value was being painted raw. If anyone ever pipes the enum
  // straight to the DOM again, this fails.
  it('never shows the word "sincronizado" anywhere in the panel', async () => {
    pxqAPI.getLive.mockResolvedValue(mockOneTier('sincronizado'));
    const { container } = renderPanel();

    await screen.findByText('Actualizado en MercadoLibre');
    expect(container.textContent).not.toMatch(/sincroniz/i);
  });
});

describe('PxqPanel — tier authoring (PR 4c)', () => {
  function mockLive({ mirror_tiers = [], live_tiers = [] } = {}) {
    return {
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers,
        mirror_tiers,
        fetched_at: '2026-08-01T10:00:00Z',
      },
    };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    // pxq.ver AND pxq.escribir both granted unless a test overrides.
    mockTienePermiso.mockImplementation(() => true);
  });

  afterEach(() => {
    mockTienePermiso.mockImplementation(() => true);
  });

  it('hides every editing affordance for a user with pxq.ver but not pxq.escribir', async () => {
    mockTienePermiso.mockImplementation((code) => code === 'pxq.ver');
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: [{ id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' }] }));

    renderPanel();

    await waitFor(() => expect(screen.getByText(/mirror local/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /agregar tramo/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /editar/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /eliminar/i })).not.toBeInTheDocument();
  });

  it('marks a tier with no shipping cost as incomplete instead of ready', async () => {
    pxqAPI.getLive.mockResolvedValue(
      mockLive({ mirror_tiers: [{ id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: null, ml_price_id: null, estado: 'listo' }] }),
    );

    renderPanel();

    await waitFor(() => expect(screen.getByText(/incompleto/i)).toBeInTheDocument());
  });

  it('creates a tier with the exact backend field shape and reloads the list', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [] }))
      .mockResolvedValueOnce(
        mockLive({ mirror_tiers: [{ id: 2, cantidad_minima: 10, precio_unitario: 200, costo_envio_total: 50, ml_price_id: null, estado: 'listo' }] }),
      );
    pxqAPI.createTier.mockResolvedValue({ data: { id: 2, cantidad_minima: 10, precio_unitario: 200, costo_envio_total: 50, ml_price_id: null, estado: 'listo' } });

    renderPanel();

    await waitFor(() => expect(screen.getByLabelText(/cantidad mínima/i)).toBeInTheDocument());
    await user.type(screen.getByLabelText(/cantidad mínima/i), '10');
    await user.type(screen.getByLabelText(/precio unitario/i), '200');
    await user.type(screen.getByLabelText(/costo de envío/i), '50');
    await user.click(screen.getByRole('button', { name: /agregar tramo/i }));

    await waitFor(() =>
      expect(pxqAPI.createTier).toHaveBeenCalledWith('MLA001', {
        cantidad_minima: 10,
        precio_unitario: 200,
        costo_envio_total: 50,
      }),
    );
    await waitFor(() => expect(pxqAPI.getLive).toHaveBeenCalledTimes(2));
  });

  it('disables "agregar tramo" once 5 tiers already exist', async () => {
    const fiveTiers = [1, 2, 3, 4, 5].map((n) => ({
      id: n,
      cantidad_minima: n * 2,
      precio_unitario: 100,
      costo_envio_total: 10,
      ml_price_id: null,
      estado: 'listo',
    }));
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: fiveTiers }));

    renderPanel();

    await waitFor(() => expect(screen.getByRole('button', { name: /agregar tramo/i })).toBeDisabled());
  });

  it('surfaces the backend 422 message on create instead of swallowing it', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: [] }));
    pxqAPI.createTier.mockRejectedValue({
      response: { status: 422, data: { detail: 'cantidad_minima duplicada' } },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByLabelText(/cantidad mínima/i)).toBeInTheDocument());
    await user.type(screen.getByLabelText(/cantidad mínima/i), '5');
    await user.type(screen.getByLabelText(/precio unitario/i), '100');
    await user.type(screen.getByLabelText(/costo de envío/i), '20');
    await user.click(screen.getByRole('button', { name: /agregar tramo/i }));

    await waitFor(() => expect(screen.getByText(/cantidad_minima duplicada/i)).toBeInTheDocument());
  });

  it('edits an existing tier through PATCH with only the changed fields shape', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive
      .mockResolvedValueOnce(
        mockLive({ mirror_tiers: [{ id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' }] }),
      )
      .mockResolvedValueOnce(
        mockLive({ mirror_tiers: [{ id: 1, cantidad_minima: 5, precio_unitario: 150, costo_envio_total: 20, ml_price_id: null, estado: 'listo' }] }),
      );
    pxqAPI.updateTier.mockResolvedValue({ data: { id: 1, cantidad_minima: 5, precio_unitario: 150, costo_envio_total: 20, ml_price_id: null, estado: 'listo' } });

    renderPanel();

    await waitFor(() => expect(screen.getByRole('button', { name: /^editar$/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /^editar$/i }));

    const precioInput = screen.getByLabelText(/precio unitario/i);
    await user.clear(precioInput);
    await user.type(precioInput, '150');
    await user.click(screen.getByRole('button', { name: /guardar/i }));

    await waitFor(() =>
      expect(pxqAPI.updateTier).toHaveBeenCalledWith('MLA001', 1, {
        cantidad_minima: 5,
        precio_unitario: 150,
        costo_envio_total: 20,
      }),
    );
  });

  it('deletes a tier only after explicit confirmation', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive
      .mockResolvedValueOnce(
        mockLive({ mirror_tiers: [{ id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' }] }),
      )
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [] }));
    pxqAPI.deleteTier.mockResolvedValue({});

    renderPanel();

    await waitFor(() => expect(screen.getByRole('button', { name: /^eliminar$/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /^eliminar$/i }));
    expect(pxqAPI.deleteTier).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: /confirmar/i }));

    await waitFor(() => expect(pxqAPI.deleteTier).toHaveBeenCalledWith('MLA001', 1));
  });
});

describe('PxqPanel — price update to ML (PR 4d)', () => {
  function mockLive({ mirror_tiers = [], live_tiers = [], live_status = 'ok' } = {}) {
    return {
      data: {
        item_id: 'MLA001',
        live_status,
        live_tiers,
        mirror_tiers,
        fetched_at: '2026-08-01T10:00:00Z',
      },
    };
  }

  const oneTier = [{ id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' }];

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockImplementation(() => true);
  });

  afterEach(() => {
    mockTienePermiso.mockImplementation(() => true);
  });

  it('hides the price-update button for a user without pxq.escribir', async () => {
    mockTienePermiso.mockImplementation((code) => code === 'pxq.ver');
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));

    renderPanel();

    await waitFor(() => expect(screen.getByText(/mirror local/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /actualizar precios en mercadolibre/i })).not.toBeInTheDocument();
  });

  it('updates prices directly (no confirm) when there are tiers to send, and reloads live state after success', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValueOnce(mockLive({ mirror_tiers: oneTier })).mockResolvedValueOnce(mockLive({ mirror_tiers: oneTier, live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 100 }] }));
    pxqAPI.sync.mockResolvedValue({ data: { synced: true, status: 'sincronizado' } });

    renderPanel();

    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    await waitFor(() => expect(pxqAPI.sync).toHaveBeenCalledTimes(1));
    expect(pxqAPI.sync).toHaveBeenCalledWith('MLA001');
    await waitFor(() => expect(pxqAPI.getLive).toHaveBeenCalledTimes(2));
  });

  // The incident: `hasTiers` was computed from the mirror alone, so an empty
  // mirror + live tiers fell through to a confirm-clear branch whose only
  // action was `runSync(true)` -> `allow_clear: true` -> a full wipe of the
  // live array. Four publications lost their tiers this way. No interaction
  // reachable from the sync control may produce a clearing call.
  it('never sends a clearing write when the mirror is empty but ML holds live tiers', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(
      mockLive({ mirror_tiers: [], live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 100 }] }),
    );
    pxqAPI.sync.mockResolvedValue({ data: { synced: true, status: 'sincronizado' } });

    renderPanel();

    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    // The write path is not reached at all in this state. That is the whole
    // assertion: the old code answered this exact situation by offering a
    // wipe, so "did not call sync" is what separates the fix from the bug.
    // The complementary guarantee — that `pxqAPI.sync` cannot express a clear
    // even if a caller tried — belongs to the API surface itself and lives in
    // `src/services/api.pxq.test.js`, where the real module is exercised.
    expect(pxqAPI.sync).not.toHaveBeenCalled();
    // The refusal used to end with "importarlos al mirror local todavía no
    // está disponible". That is now false — `PxqAdoptControl` renders in
    // exactly this state — so the assertion moved to the sentence that
    // replaced it, naming the control by its button label. Matching on the
    // label is deliberate: if the button is ever renamed, the message that
    // points at it must be renamed in the same commit.
    expect(
      screen.getByText(/si los querés en el mirror, importalos con "Importar de MercadoLibre", acá arriba/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/todavía no está disponible/i)).not.toBeInTheDocument();
  });

  it('refuses distinctly when neither side has tiers (nothing to update)', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: [], live_tiers: [] }));

    renderPanel();

    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    expect(pxqAPI.sync).not.toHaveBeenCalled();
    expect(screen.getByText(/no hay precios para actualizar/i)).toBeInTheDocument();
    // Retargeted onto the copy that replaced the old "todavía no está
    // disponible" sentence: with both sides empty there is nothing to import,
    // so the refusal must not send the operator to the import control.
    expect(screen.queryByText(/importalos con "Importar de MercadoLibre"/i)).not.toBeInTheDocument();
  });

  it('refuses distinctly when the mirror is empty and the live state could not be read', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(
      mockLive({ mirror_tiers: [], live_tiers: null, live_status: 'unavailable' }),
    );

    renderPanel();

    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    expect(pxqAPI.sync).not.toHaveBeenCalled();
    expect(screen.getByText(/no se pudo leer el estado en vivo de mercadolibre, así que no se va a tocar nada/i)).toBeInTheDocument();
    expect(screen.queryByText(/no hay precios para actualizar/i)).not.toBeInTheDocument();
  });

  it('shows the feature-disabled message distinctly from a permissions problem (503 disabled)', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 503, data: { detail: { status: 'disabled' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/deshabilitada/i)).toBeInTheDocument());
    expect(screen.queryByText(/no tenés permiso/i)).not.toBeInTheDocument();
  });

  it('shows a permissions message on 403, distinct from the feature being disabled', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 403, data: { detail: 'No tienes permiso: pxq.escribir' } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/no tenés permiso/i)).toBeInTheDocument());
  });

  it('shows a permanent not-eligible message on 422 rejected_not_eligible', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 422, data: { detail: { status: 'rejected_not_eligible' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/no está habilitada para precios mayoristas/i)).toBeInTheDocument());
  });

  it('shows a retry-friendly message on 503 rejected_eligibility_unknown (transient, not permanent)', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 503, data: { detail: { status: 'rejected_eligibility_unknown' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/no se pudo confirmar si esta publicación está habilitada/i)).toBeInTheDocument());
  });

  it('shows a distinct message when the live read failed so nothing was written (503 rejected_read_unavailable)', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 503, data: { detail: { status: 'rejected_read_unavailable' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/no se pudo leer el estado actual en mercadolibre/i)).toBeInTheDocument());
  });

  it('shows the divergence banner with both live and desired sides on 409, and does not auto-resolve or force', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            status: 'divergence',
            divergences: [
              {
                ml_price_id: 'PXQ1',
                reason: 'amount_mismatch',
                live: { quantity: 5, amount: 150 },
                desired: { quantity: 5, amount: 100 },
              },
            ],
          },
        },
      },
    });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/amount_mismatch/i)).toBeInTheDocument());
    expect(screen.getByText(/150/)).toBeInTheDocument();
    expect(screen.getAllByText(/100/).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /forzar/i })).not.toBeInTheDocument();
  });

  it('shows a not-a-failure-not-a-success message on 502 submitted_unconfirmed and does not claim success', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 502, data: { detail: { status: 'submitted_unconfirmed' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/no se pudo confirmar/i)).toBeInTheDocument());
    expect(screen.queryByText(/precios actualizados/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^error$/i)).not.toBeInTheDocument();
  });

  it('shows the same unconfirmed message on 502 ambiguous_needs_reconcile', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 502, data: { detail: { status: 'ambiguous_needs_reconcile' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/no se pudo confirmar/i)).toBeInTheDocument());
  });

  it('shows the MercadoLibre-rejected message on 422 rejected_by_proxy', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 422, data: { detail: { status: 'rejected_by_proxy', reason: 'invalid amount' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /actualizar precios en mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/mercadolibre rechazó/i)).toBeInTheDocument());
  });
});

describe('PxqPanel — adopt-live import (PR 4e)', () => {
  function mockLive({ mirror_tiers = [], live_tiers = [], live_status = 'ok' } = {}) {
    return {
      data: { item_id: 'MLA001', live_status, live_tiers, mirror_tiers, fetched_at: '2026-08-05T10:00:00Z' },
    };
  }

  const liveOnly = { mirror_tiers: [], live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 100 }] };
  const IMPORT_BUTTON = { name: /^importar de mercadolibre$/i };

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockImplementation(() => true);
  });

  afterEach(() => {
    mockTienePermiso.mockImplementation(() => true);
  });

  // --- mounting -------------------------------------------------------------
  // Three states where the button would be a dead action. The user must not
  // discover that by pressing it.

  it('mounts only when the mirror is empty and ML holds live tiers', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    renderPanel();
    expect(await screen.findByRole('button', IMPORT_BUTTON)).toBeInTheDocument();
  });

  it('does NOT mount when the mirror already has rows (the API would refuse with 409)', async () => {
    pxqAPI.getLive.mockResolvedValue(
      mockLive({
        mirror_tiers: [{ id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' }],
        live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 100 }],
      }),
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText(/mirror local/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', IMPORT_BUTTON)).not.toBeInTheDocument();
  });

  it('does NOT mount when ML genuinely has no tiers (nothing to import)', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: [], live_tiers: [] }));
    renderPanel();

    await waitFor(() => expect(screen.getByText(/mirror local/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', IMPORT_BUTTON)).not.toBeInTheDocument();
  });

  it('does NOT mount when the live read failed (we do not know what is there)', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: [], live_tiers: null, live_status: 'unavailable' }));
    renderPanel();

    await waitFor(() => expect(screen.getByText(/mirror local/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', IMPORT_BUTTON)).not.toBeInTheDocument();
  });

  it('hides the import button for a user without pxq.escribir', async () => {
    mockTienePermiso.mockImplementation((code) => code === 'pxq.ver');
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    renderPanel();

    await waitFor(() => expect(screen.getByText(/mirror local/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', IMPORT_BUTTON)).not.toBeInTheDocument();
  });

  // --- outcomes -------------------------------------------------------------

  it('names the imported count AND the shipping cost still required before updating prices', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive(liveOnly))
      .mockResolvedValueOnce(
        mockLive({
          mirror_tiers: [{ id: 9, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: null, ml_price_id: 'PXQ1', estado: 'incompleto' }],
          live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 100 }],
        }),
      );
    pxqAPI.adoptLive.mockResolvedValue({ data: { item_id: 'MLA001', count: 2, imported: [] } });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    await waitFor(() => expect(pxqAPI.adoptLive).toHaveBeenCalledWith('MLA001'));
    // The count is not decoration: it is the only confirmation of how much
    // was actually recovered.
    const message = await screen.findByText(/se importaron 2 tramos/i);
    // And the trap this copy exists to close — the rows land with
    // `costo_envio_total` NULL and cannot be written back to ML until it is
    // set. Asserted on the message node, not on the document: "Costo de envío
    // del bulto" is also the authoring form's field label, so a document-wide
    // matcher would pass on the wrong element.
    expect(message).toHaveTextContent(/todavía no podés actualizar precios con ellos/i);
    expect(message).toHaveTextContent(/cargá el costo de envío del bulto en cada uno/i);
  });

  it('refreshes the panel after a successful import', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    pxqAPI.adoptLive.mockResolvedValue({ data: { item_id: 'MLA001', count: 1, imported: [] } });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    await waitFor(() => expect(pxqAPI.getLive).toHaveBeenCalledTimes(2));
  });

  it('does NOT refresh the panel when the import was refused', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    pxqAPI.adoptLive.mockRejectedValue({
      response: { status: 503, data: { detail: { status: 'adopt_read_unavailable', reason: 'read failed' } } },
    });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    await waitFor(() => expect(screen.getByText(/no se importó nada/i)).toBeInTheDocument());
    expect(pxqAPI.getLive).toHaveBeenCalledTimes(1);
  });

  // The refusal that has to survive a rename most of all: the payload names
  // the rows to delete, and a message that dropped them would leave the
  // operator hunting through the mirror column by hand.
  it('names every conflicting quantity and tier id on 409', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    pxqAPI.adoptLive.mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            status: 'adopt_conflict',
            reason: 'The local mirror already has tiers for this publication',
            conflicts: [
              { tier_id: 3, cantidad_minima: 12 },
              { tier_id: 7, cantidad_minima: 24 },
            ],
          },
        },
      },
    });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    const message = await screen.findByText(/el mirror local ya tiene tramos/i);
    expect(message).toHaveTextContent('12 u. (id 3)');
    expect(message).toHaveTextContent('24 u. (id 7)');
    // The delete-then-import window, stated rather than walked into blind.
    expect(message).toHaveTextContent(/entre el borrado y la importación el mirror queda vacío/i);
    // …and the reassurance that makes the window survivable: ML is untouched.
    expect(message).toHaveTextContent(/no se tocan en ningún caso/i);
  });

  it('renders the 503 unreadable-live refusal in the warn tone, not the error tone', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    pxqAPI.adoptLive.mockRejectedValue({
      response: { status: 503, data: { detail: { status: 'adopt_read_unavailable', reason: 'read failed' } } },
    });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    const message = await screen.findByText(/no se pudo leer el estado en vivo de mercadolibre, así que no se importó nada/i);
    expect(message).toHaveTextContent(/podés reintentar/i);
    // Transient, so it must not be painted as a failure the operator caused.
    // The class is the only carrier of that distinction in the DOM; the visual
    // suite proves the three classes actually paint differently.
    expect(message.className).toMatch(/feedbackWarn/);
    expect(message.className).not.toMatch(/feedbackError/);
  });

  it('shows a permissions message on 403, distinct from every other refusal', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    pxqAPI.adoptLive.mockRejectedValue({ response: { status: 403, data: { detail: 'No tienes permiso: pxq.escribir' } } });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    expect(await screen.findByText(/no tenés permiso para importar tramos/i)).toBeInTheDocument();
    expect(screen.queryByText(/no se pudo leer el estado en vivo/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/el mirror local ya tiene tramos/i)).not.toBeInTheDocument();
  });

  it('shows a distinct message on 404 for an item the backend does not know', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    pxqAPI.adoptLive.mockRejectedValue({ response: { status: 404, data: { detail: 'Publicación no encontrada' } } });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    expect(await screen.findByText(/no se encontró esta publicación/i)).toBeInTheDocument();
    expect(screen.queryByText(/no tenés permiso/i)).not.toBeInTheDocument();
  });

  // 200 with count 0 is reachable: the mount condition reads the live state
  // fetched when the panel opened, and ML can lose its tiers before the click.
  it('does not claim an import happened when ML turned out to have nothing left', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    pxqAPI.adoptLive.mockResolvedValue({ data: { item_id: 'MLA001', count: 0, imported: [] } });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    expect(await screen.findByText(/ya no tiene tramos mayoristas para importar/i)).toBeInTheDocument();
    expect(screen.queryByText(/se importaron 0/i)).not.toBeInTheDocument();
    // No next step is named, because no rows were created to have one.
    expect(screen.queryByText(/cargá el costo de envío del bulto/i)).not.toBeInTheDocument();
  });

  it('disables the button while the import is in flight', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    let resolveAdopt;
    pxqAPI.adoptLive.mockReturnValue(
      new Promise((resolve) => {
        resolveAdopt = resolve;
      }),
    );

    renderPanel();
    const button = await screen.findByRole('button', IMPORT_BUTTON);
    await user.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    // A second click cannot start a second import.
    await user.click(button);
    expect(pxqAPI.adoptLive).toHaveBeenCalledTimes(1);

    resolveAdopt({ data: { item_id: 'MLA001', count: 1, imported: [] } });
    // Re-queried, not reused: the success path reloads the panel, which
    // remounts the subtree, so `button` above is a detached node by now.
    expect(await screen.findByText(/se importó 1 tramo/i)).toBeInTheDocument();
    expect(screen.getByRole('button', IMPORT_BUTTON)).not.toBeDisabled();
  });

  // The outcome message deliberately outlives `reload()` (the reload unmounts
  // the control, so local state would take the message with it — see the
  // control's docstring). It must NOT also outlive the publication: the panel
  // is re-keyed on a new `itemId` WITHOUT unmounting, so an uncleared message
  // would go on describing an import that happened somewhere else.
  it('clears the import outcome when the panel moves to another publication', async () => {
    const user = userEvent.setup();
    const pxqCacheRef = { current: new Map() };
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    pxqAPI.adoptLive.mockResolvedValue({ data: { item_id: 'MLA001', count: 2, imported: [] } });

    const { rerender } = render(<PxqPanel itemId="MLA001" pxqCacheRef={pxqCacheRef} />);
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));
    expect(await screen.findByText(/se importaron 2 tramos/i)).toBeInTheDocument();

    rerender(<PxqPanel itemId="MLA002" pxqCacheRef={pxqCacheRef} />);

    // Asserted AFTER the new publication has finished loading, not during the
    // loading branch: the loading branch hides everything, so checking there
    // would pass even with the message still held in state.
    await waitFor(() => expect(pxqAPI.getLive).toHaveBeenLastCalledWith('MLA002'));
    await screen.findByText(/mirror local/i);
    expect(screen.queryByText(/se importaron 2 tramos/i)).not.toBeInTheDocument();
  });

  // The label is the whole point of the control existing separately: it says
  // what it does. "Sincronizar" is the verb that destroyed four publications,
  // and it is now gone from both directions of this panel — but the assertion
  // stays, because a future rename must not reintroduce it here either.
  it('never labels the import as a sync', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    renderPanel();

    const button = await screen.findByRole('button', IMPORT_BUTTON);
    expect(button).toHaveTextContent('Importar de MercadoLibre');
    expect(button.textContent).not.toMatch(/sincroniz/i);
    expect(button.className).toMatch(/\bprimary\b/);
  });
});

describe('PxqPanel — primary actions look like buttons', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
  });

  it('renders "Agregar tramo" and "Actualizar precios" with the primary variant, not the bare base', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [],
        mirror_tiers: [],
        fetched_at: '2026-08-03T12:00:00Z',
      },
    });
    renderPanel();

    const agregar = await screen.findByRole('button', { name: /agregar tramo/i });
    const actualizar = screen.getByRole('button', { name: /actualizar precios en mercadolibre/i });

    // The bare `btn-tesla` base is `background: transparent` with a
    // transparent border, so on the panel's grey it reads as text. These two
    // are the primary actions of the panel — one of them writes to ML.
    for (const button of [agregar, actualizar]) {
      expect(button.className).toMatch(/\bprimary\b/);
    }
  });
});
