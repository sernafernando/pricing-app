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

vi.mock('../../services/api', () => ({
  pxqAPI: {
    getLive: vi.fn(),
    createTier: vi.fn(),
    updateTier: vi.fn(),
    deleteTier: vi.fn(),
    sync: vi.fn(),
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

    await waitFor(() => expect(screen.getByText(/en mercadolibre/i)).toBeInTheDocument());
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
    // A regular sync action existing elsewhere in the panel is fine (PR 4d) —
    // what this read-only comparison must never offer is an inline
    // "resolver"/auto-fix action right next to the divergent row itself.
    expect(screen.queryByRole('button', { name: /^resolver$/i })).not.toBeInTheDocument();
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

describe('PxqPanel — sync (PR 4d)', () => {
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

  const oneTier = [{ id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' }];

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockImplementation(() => true);
  });

  afterEach(() => {
    mockTienePermiso.mockImplementation(() => true);
  });

  it('hides the sync button for a user without pxq.escribir', async () => {
    mockTienePermiso.mockImplementation((code) => code === 'pxq.ver');
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));

    renderPanel();

    await waitFor(() => expect(screen.getByText(/mirror local/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /sincronizar con mercadolibre/i })).not.toBeInTheDocument();
  });

  it('syncs directly (no confirm) when there are tiers to send, and reloads live state after success', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValueOnce(mockLive({ mirror_tiers: oneTier })).mockResolvedValueOnce(mockLive({ mirror_tiers: oneTier, live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 100 }] }));
    pxqAPI.sync.mockResolvedValue({ data: { synced: true, status: 'sincronizado' } });

    renderPanel();

    await waitFor(() => expect(screen.getByRole('button', { name: /sincronizar con mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /sincronizar con mercadolibre/i }));

    await waitFor(() => expect(pxqAPI.sync).toHaveBeenCalledWith('MLA001', false));
    await waitFor(() => expect(pxqAPI.getLive).toHaveBeenCalledTimes(2));
  });

  it('requires an explicit confirmation before syncing an empty tier list (clearing everything on ML)', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: [] }));
    pxqAPI.sync.mockResolvedValue({ data: { synced: true, status: 'sincronizado' } });

    renderPanel();

    await waitFor(() => expect(screen.getByRole('button', { name: /sincronizar con mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /sincronizar con mercadolibre/i }));

    expect(pxqAPI.sync).not.toHaveBeenCalled();
    expect(screen.getByText(/todos los tramos mayoristas van a desaparecer de la publicación/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /confirmar/i }));

    await waitFor(() => expect(pxqAPI.sync).toHaveBeenCalledWith('MLA001', true));
  });

  it('shows the feature-disabled message distinctly from a permissions problem (503 disabled)', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 503, data: { detail: { status: 'disabled' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /sincronizar con mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /sincronizar con mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/deshabilitada/i)).toBeInTheDocument());
    expect(screen.queryByText(/no tenés permiso/i)).not.toBeInTheDocument();
  });

  it('shows a permissions message on 403, distinct from the feature being disabled', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 403, data: { detail: 'No tienes permiso: pxq.escribir' } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /sincronizar con mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /sincronizar con mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/no tenés permiso/i)).toBeInTheDocument());
  });

  it('shows a permanent not-eligible message on 422 rejected_not_eligible', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 422, data: { detail: { status: 'rejected_not_eligible' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /sincronizar con mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /sincronizar con mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/no está habilitada para precios mayoristas/i)).toBeInTheDocument());
  });

  it('shows a retry-friendly message on 503 rejected_eligibility_unknown (transient, not permanent)', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 503, data: { detail: { status: 'rejected_eligibility_unknown' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /sincronizar con mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /sincronizar con mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/no se pudo confirmar si esta publicación está habilitada/i)).toBeInTheDocument());
  });

  it('shows a distinct message when the live read failed so nothing was written (503 rejected_read_unavailable)', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 503, data: { detail: { status: 'rejected_read_unavailable' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /sincronizar con mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /sincronizar con mercadolibre/i }));

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
    await waitFor(() => expect(screen.getByRole('button', { name: /sincronizar con mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /sincronizar con mercadolibre/i }));

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
    await waitFor(() => expect(screen.getByRole('button', { name: /sincronizar con mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /sincronizar con mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/no se pudo confirmar/i)).toBeInTheDocument());
    expect(screen.queryByText(/sincronizado con éxito/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^error$/i)).not.toBeInTheDocument();
  });

  it('shows the same unconfirmed message on 502 ambiguous_needs_reconcile', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 502, data: { detail: { status: 'ambiguous_needs_reconcile' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /sincronizar con mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /sincronizar con mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/no se pudo confirmar/i)).toBeInTheDocument());
  });

  it('shows the MercadoLibre-rejected message on 422 rejected_by_proxy', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.sync.mockRejectedValue({ response: { status: 422, data: { detail: { status: 'rejected_by_proxy', reason: 'invalid amount' } } } });

    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: /sincronizar con mercadolibre/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /sincronizar con mercadolibre/i }));

    await waitFor(() => expect(screen.getByText(/mercadolibre rechazó/i)).toBeInTheDocument());
  });
});

describe('PxqPanel — primary actions look like buttons', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
  });

  it('renders "Agregar tramo" and "Sincronizar" with the primary variant, not the bare base', async () => {
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
    const sincronizar = screen.getByRole('button', { name: /sincronizar con mercadolibre/i });

    // The bare `btn-tesla` base is `background: transparent` with a
    // transparent border, so on the panel's grey it reads as text. These two
    // are the primary actions of the panel — one of them writes to ML.
    for (const button of [agregar, sincronizar]) {
      expect(button.className).toMatch(/\bprimary\b/);
    }
  });
});
