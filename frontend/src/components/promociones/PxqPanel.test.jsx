import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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
    getMarkup: vi.fn(),
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

  // The row adopt-live writes for a "Venta para negocios" price: quantity 1,
  // no shipping cost, `incompleto`. The import's own success copy tells the
  // operator to load `costo_envio_total` on exactly this row, so the form has
  // to accept it — the quantity input's `min` gates the WHOLE row through
  // native constraint validation, not just its own field. With `min="2"` the
  // value "1" raises rangeUnderflow and the submit never fires, so the panel
  // would demand a next step it physically refuses to take.
  it('lets the operator complete a one-unit tier the import just wrote', async () => {
    const user = userEvent.setup();
    const imported = {
      id: 9,
      cantidad_minima: 1,
      precio_unitario: 80999,
      costo_envio_total: null,
      ml_price_id: '3396',
      estado: 'incompleto',
    };
    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [imported] }))
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [{ ...imported, costo_envio_total: 30, estado: 'listo' }] }));
    pxqAPI.updateTier.mockResolvedValue({ data: { ...imported, costo_envio_total: 30 } });

    renderPanel();

    await waitFor(() => expect(screen.getByRole('button', { name: /^editar$/i })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /^editar$/i }));

    // The quantity stays at 1: the operator is completing the row, not fixing it.
    await user.type(screen.getByLabelText(/costo de envío/i), '30');
    await user.click(screen.getByRole('button', { name: /guardar/i }));

    await waitFor(() =>
      expect(pxqAPI.updateTier).toHaveBeenCalledWith('MLA001', 9, {
        cantidad_minima: 1,
        precio_unitario: 80999,
        costo_envio_total: 30,
      }),
    );
  });

  // Same gate on the creation form. A tier of 1 is what turns "Venta para
  // negocios" on, so authoring one by hand has to be possible too.
  it('lets the operator author a one-unit tier by hand', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [] }))
      .mockResolvedValueOnce(
        mockLive({
          mirror_tiers: [
            { id: 3, cantidad_minima: 1, precio_unitario: 80999, costo_envio_total: 30, ml_price_id: null, estado: 'listo' },
          ],
        }),
      );
    pxqAPI.createTier.mockResolvedValue({
      data: { id: 3, cantidad_minima: 1, precio_unitario: 80999, costo_envio_total: 30, ml_price_id: null, estado: 'listo' },
    });

    renderPanel();

    await screen.findByText('Editar tramos');
    await user.type(screen.getByLabelText(/cantidad mínima/i), '1');
    await user.type(screen.getByLabelText(/precio unitario/i), '80999');
    await user.type(screen.getByLabelText(/costo de envío/i), '30');
    await user.click(screen.getByRole('button', { name: /agregar tramo/i }));

    await waitFor(() =>
      expect(pxqAPI.createTier).toHaveBeenCalledWith('MLA001', {
        cantidad_minima: 1,
        precio_unitario: 80999,
        costo_envio_total: 30,
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
    // `skipped_count: 0` is explicit, not incidental: this is the ONLY branch
    // still allowed to claim MercadoLibre has nothing.
    pxqAPI.adoptLive.mockResolvedValue({ data: { item_id: 'MLA001', count: 0, imported: [], skipped_count: 0, skipped: [] } });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    expect(await screen.findByText(/ya no tiene tramos mayoristas para importar/i)).toBeInTheDocument();
    expect(screen.queryByText(/se importaron 0/i)).not.toBeInTheDocument();
    // No next step is named, because no rows were created to have one.
    expect(screen.queryByText(/cargá el costo de envío del bulto/i)).not.toBeInTheDocument();
  });

  // The skip survives, its trigger moved. A one-unit tier is imported now —
  // it is what turns on "Venta para negocios" on MercadoLibre — so the only
  // thing left that this mirror cannot represent is a quantity below 1. The
  // copy has to state THAT rule, because a sentence naming the old floor would
  // be a false explanation for a gap the operator can see on screen.
  it('names the skipped price alongside the imported count', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    pxqAPI.adoptLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        count: 2,
        imported: [],
        skipped_count: 1,
        skipped: [{ ml_price_id: '3396', cantidad_minima: 0 }],
      },
    });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    const message = await screen.findByText(/se importaron 2 tramos/i);
    // The success copy is not replaced by the skip — both facts are true and
    // the operator needs both.
    expect(message).toHaveTextContent(/cargá el costo de envío del bulto en cada uno/i);
    expect(message).toHaveTextContent(/no se importó/i);
    expect(message).toHaveTextContent(/no llega a 1 unidad/i);
    // The old floor must be GONE from the copy, not merely joined by the new
    // one: it now describes a rule the backend no longer applies.
    expect(message).not.toHaveTextContent(/menos de 2 unidades/i);
    expect(message).not.toHaveTextContent(/tramos desde 2/i);
    // And the reassurance that matters on a money path: skipping is not
    // deleting. `pxq_diff` re-emits every untracked live tier as a keep.
    expect(message).toHaveTextContent(/sigue.*mercadolibre/i);
  });

  // The branch that used to LIE. `count === 0` alone routed to "MercadoLibre
  // ya no tiene tramos mayoristas", and with a skip present that is false:
  // ML has a price, it is this panel that cannot represent it.
  it('does not claim MercadoLibre has nothing when everything was skipped', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive(liveOnly));
    pxqAPI.adoptLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        count: 0,
        imported: [],
        skipped_count: 1,
        skipped: [{ ml_price_id: '3396', cantidad_minima: 0 }],
      },
    });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    const message = await screen.findByText(/no se importó nada/i);
    expect(message).toHaveTextContent(/no llega a 1 unidad/i);
    expect(screen.queryByText(/ya no tiene tramos mayoristas/i)).not.toBeInTheDocument();
    // Nothing landed, so there is no shipping cost to go and load.
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

// An outcome message has to outlive the reload IT triggered — the reload is
// what makes the outcome visible in the columns above, and it unmounts the
// control that produced the message. It must NOT outlive its own truth: the
// moment the operator edits the mirror the message describes, the message stops
// describing what is on screen.
//
// Both halves are asserted here because they pull in opposite directions, and a
// "simplification" that clears feedback inside `reload()` satisfies the second
// while silently destroying the first.
describe('PxqPanel — outcome messages outlive their reload, not their truth', () => {
  function mockLive({ mirror_tiers = [], live_tiers = [], live_status = 'ok', item_id = 'MLA001' } = {}) {
    return {
      data: { item_id, live_status, live_tiers, mirror_tiers, fetched_at: '2026-08-06T10:00:00Z' },
    };
  }

  const importedTier = [{ id: 9, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: null, ml_price_id: 'PXQ1', estado: 'incompleto' }];
  const liveTiers = [{ id: 'PXQ1', quantity: 5, amount: 100 }];

  const IMPORT_BUTTON = { name: /^importar de mercadolibre$/i };

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockImplementation(() => true);
  });

  afterEach(() => {
    mockTienePermiso.mockImplementation(() => true);
  });



  // The guardrail for the clearing rule. The import's OWN reload is the reason
  // this state was lifted to the panel in the first place; anyone who
  // "simplifies" by clearing feedback inside `reload()` breaks this.
  it('does not clear the import message on the reload the import itself triggers', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [], live_tiers: liveTiers }))
      .mockResolvedValueOnce(mockLive({ mirror_tiers: importedTier, live_tiers: liveTiers }));
    pxqAPI.adoptLive.mockResolvedValue({ data: { item_id: 'MLA001', count: 2, imported: [] } });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));

    await waitFor(() => expect(pxqAPI.getLive).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/se importaron 2 tramos/i)).toBeInTheDocument();
  });

  // "Cargá el costo de envío del bulto" stops being true the instant he does.
  it('clears the import message once the operator edits a tier', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [], live_tiers: liveTiers }))
      .mockResolvedValueOnce(mockLive({ mirror_tiers: importedTier, live_tiers: liveTiers }))
      .mockResolvedValue(
        mockLive({
          mirror_tiers: [{ id: 9, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 30, ml_price_id: 'PXQ1', estado: 'listo' }],
          live_tiers: liveTiers,
        }),
      );
    pxqAPI.adoptLive.mockResolvedValue({ data: { item_id: 'MLA001', count: 2, imported: [] } });
    pxqAPI.updateTier.mockResolvedValue({ data: {} });

    renderPanel();
    await user.click(await screen.findByRole('button', IMPORT_BUTTON));
    expect(await screen.findByText(/se importaron 2 tramos/i)).toBeInTheDocument();

    // The exact next step the message named: load the shipping cost.
    await user.click(await screen.findByRole('button', { name: /^editar$/i }));
    await user.type(screen.getByLabelText(/costo de envío/i), '30');
    await user.click(screen.getByRole('button', { name: /guardar/i }));

    await waitFor(() => expect(pxqAPI.updateTier).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText(/se importaron 2 tramos/i)).not.toBeInTheDocument());
  });


  // A message may outlive its control, never its PUBLICATION. The cache for the
  // second item is warmed on purpose so the move does NOT pass through the
  // loading branch: an unmount would hide a stale message by accident, and this
  // test has to prove the reset itself.
  it('clears the import outcome when the panel moves to another publication', async () => {
    const user = userEvent.setup();
    const pxqCacheRef = { current: new Map() };
    pxqCacheRef.current.set('MLA002', {
      status: 'ok',
      data: { item_id: 'MLA002', live_status: 'ok', live_tiers: [], mirror_tiers: [], fetched_at: '2026-08-06T10:00:00Z' },
    });

    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [], live_tiers: liveTiers }))
      .mockResolvedValueOnce(mockLive({ mirror_tiers: importedTier, live_tiers: liveTiers }));
    pxqAPI.adoptLive.mockResolvedValue({ data: { item_id: 'MLA001', count: 2, imported: [] } });

    const { rerender } = render(<PxqPanel itemId="MLA001" pxqCacheRef={pxqCacheRef} />);

    await user.click(await screen.findByRole('button', IMPORT_BUTTON));
    expect(await screen.findByText(/se importaron 2 tramos/i)).toBeInTheDocument();

    rerender(<PxqPanel itemId="MLA002" pxqCacheRef={pxqCacheRef} />);

    await waitFor(() => expect(screen.queryByText(/se importaron 2 tramos/i)).not.toBeInTheDocument());
  });
});

// A delete is the one authoring action whose failure path never reloads, so
// the ONLY thing the operator gets back is the inline message. When that
// message does not render, pressing "Confirmar" produces literally no feedback
// and the tier stays on screen — indistinguishable from a click that never
// registered.
describe('PxqPanel — a failed tier delete is visible, and only on the row that failed', () => {
  function mockLive({ mirror_tiers = [], live_tiers = [] } = {}) {
    return {
      data: { item_id: 'MLA001', live_status: 'ok', live_tiers, mirror_tiers, fetched_at: '2026-08-07T10:00:00Z' },
    };
  }

  const twoTiers = [
    { id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' },
    { id: 2, cantidad_minima: 10, precio_unitario: 90, costo_envio_total: 30, ml_price_id: null, estado: 'listo' },
  ];

  const DELETE_FAILED = /el tramo tiene ventas asociadas/i;
  const deleteRejection = {
    response: { status: 409, data: { detail: 'El tramo tiene ventas asociadas.' } },
  };

  // Two tiers on purpose. With one row the "shows on the failing row" and
  // "shows everywhere" behaviours are indistinguishable, which is how a
  // one-string-for-the-whole-list error survived review in the first place.
  async function failDeleteOnFirstTier(user) {
    const eliminar = await screen.findAllByRole('button', { name: /^eliminar$/i });
    expect(eliminar).toHaveLength(2);
    await user.click(eliminar[0]);
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));
    await waitFor(() => expect(pxqAPI.deleteTier).toHaveBeenCalledWith('MLA001', 1));
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockImplementation(() => true);
  });

  afterEach(() => {
    mockTienePermiso.mockImplementation(() => true);
  });

  it('renders the backend message when confirming a delete that fails', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: twoTiers }));
    pxqAPI.deleteTier.mockRejectedValue(deleteRejection);

    renderPanel();
    await failDeleteOnFirstTier(user);

    expect(await screen.findByText(DELETE_FAILED)).toBeInTheDocument();
  });

  it('renders the delete error once, on the row that failed, not on every row', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: twoTiers }));
    pxqAPI.deleteTier.mockRejectedValue(deleteRejection);

    renderPanel();
    await failDeleteOnFirstTier(user);

    await screen.findByText(DELETE_FAILED);
    expect(screen.getAllByText(DELETE_FAILED)).toHaveLength(1);
  });

  // The confirmation staying open after a failure is DELIBERATE, not an
  // oversight: the retry and the escape hatch have to be reachable without
  // hunting for the row again, with the reason still on screen.
  it('keeps the confirmation open after a failure so the operator can retry or cancel', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: twoTiers }));
    pxqAPI.deleteTier.mockRejectedValue(deleteRejection);

    renderPanel();
    await failDeleteOnFirstTier(user);

    await screen.findByText(DELETE_FAILED);
    expect(screen.getByRole('button', { name: /^confirmar$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^cancelar$/i })).toBeInTheDocument();
  });

  it('clears the delete error when the operator cancels', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: twoTiers }));
    pxqAPI.deleteTier.mockRejectedValue(deleteRejection);

    renderPanel();
    await failDeleteOnFirstTier(user);
    await screen.findByText(DELETE_FAILED);

    await user.click(screen.getByRole('button', { name: /^cancelar$/i }));

    expect(screen.queryByText(DELETE_FAILED)).not.toBeInTheDocument();
  });

  // Otherwise a failure on tier 1 keeps accusing tier 1 while the operator is
  // already looking at the confirmation for tier 2.
  it('clears the delete error when the operator starts deleting another tier', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: twoTiers }));
    pxqAPI.deleteTier.mockRejectedValue(deleteRejection);

    renderPanel();
    await failDeleteOnFirstTier(user);
    await screen.findByText(DELETE_FAILED);

    // While tier 1 sits in confirmation, tier 2 is the only row still offering
    // "Eliminar", so this query is unambiguous.
    await user.click(screen.getByRole('button', { name: /^eliminar$/i }));

    expect(screen.queryByText(DELETE_FAILED)).not.toBeInTheDocument();
  });

  it('leaves no error and closes the confirmation after a delete that succeeds', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: twoTiers }))
      .mockResolvedValue(mockLive({ mirror_tiers: [twoTiers[1]] }));
    pxqAPI.deleteTier.mockResolvedValue({});

    renderPanel();
    await failDeleteOnFirstTier(user);

    await waitFor(() => expect(pxqAPI.getLive).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(DELETE_FAILED)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^confirmar$/i })).not.toBeInTheDocument();
  });

  // Making the failure VISIBLE is what forces this block to exist. "Confirmar"
  // was never disabled, so a double click always sent two DELETEs — the second
  // one 404s because the first already succeeded. That second failure used to
  // be swallowed by the same invisible-error defect; now it would be painted
  // on the row, so the fix above would have turned a harmless race into a
  // fabricated error message.
  it('disables "Confirmar" while the delete is in flight', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: twoTiers }));
    let rejectDelete;
    pxqAPI.deleteTier.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectDelete = reject;
      }),
    );

    renderPanel();
    const eliminar = await screen.findAllByRole('button', { name: /^eliminar$/i });
    await user.click(eliminar[0]);
    const confirmar = screen.getByRole('button', { name: /^confirmar$/i });
    await user.click(confirmar);

    await waitFor(() => expect(confirmar).toBeDisabled());

    rejectDelete(deleteRejection);
    await screen.findByText(DELETE_FAILED);
  });

  it('fires exactly one DELETE when "Confirmar" is clicked twice in a row', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: twoTiers }))
      .mockResolvedValue(mockLive({ mirror_tiers: [twoTiers[1]] }));
    let resolveDelete;
    pxqAPI.deleteTier.mockReturnValue(
      new Promise((resolve) => {
        resolveDelete = resolve;
      }),
    );

    renderPanel();
    const eliminar = await screen.findAllByRole('button', { name: /^eliminar$/i });
    await user.click(eliminar[0]);
    const confirmar = screen.getByRole('button', { name: /^confirmar$/i });
    await user.click(confirmar);
    await user.click(confirmar);

    expect(pxqAPI.deleteTier).toHaveBeenCalledTimes(1);

    resolveDelete({});
    await waitFor(() => expect(pxqAPI.getLive).toHaveBeenCalledTimes(2));
  });

  // The in-flight flag is cleared in a `finally`; `setDeletingId(null)` is not.
  // They answer different questions — "is a request outstanding" versus "is the
  // confirmation still open" — and collapsing them would either kill the retry
  // button or close the confirmation on failure.
  it('re-enables "Confirmar" after a failure so the delete can be retried', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: twoTiers }));
    pxqAPI.deleteTier.mockRejectedValue(deleteRejection);

    renderPanel();
    await failDeleteOnFirstTier(user);
    await screen.findByText(DELETE_FAILED);

    const confirmar = screen.getByRole('button', { name: /^confirmar$/i });
    expect(confirmar).toBeEnabled();

    await user.click(confirmar);
    await waitFor(() => expect(pxqAPI.deleteTier).toHaveBeenCalledTimes(2));
  });
});

// `extractErrorMessage` is shared by create, edit and delete, so a single
// hardcoded fallback is guaranteed to lie to two of the three callers. It only
// started to matter once the delete error became visible at all: before that,
// "No se pudo guardar el tramo." on a delete was a string nobody ever read.
describe('PxqPanel — the unparseable-error fallback names the action that failed', () => {
  function mockLive({ mirror_tiers = [], live_tiers = [] } = {}) {
    return {
      data: { item_id: 'MLA001', live_status: 'ok', live_tiers, mirror_tiers, fetched_at: '2026-08-07T10:00:00Z' },
    };
  }

  const oneTier = [{ id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' }];

  // A raw 500: no `detail` at all, so neither the string branch nor the
  // `.reason` branch of `extractErrorMessage` can produce anything.
  const unparseable = { response: { status: 500, data: {} } };

  const SAVE_FALLBACK = /^no se pudo guardar el tramo\.$/i;
  const DELETE_FALLBACK = /^no se pudo eliminar el tramo\.$/i;

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockImplementation(() => true);
  });

  afterEach(() => {
    mockTienePermiso.mockImplementation(() => true);
  });

  it('says the tier could not be DELETED when a delete fails unparseably', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.deleteTier.mockRejectedValue(unparseable);

    renderPanel();
    await user.click(await screen.findByRole('button', { name: /^eliminar$/i }));
    await user.click(screen.getByRole('button', { name: /^confirmar$/i }));

    expect(await screen.findByText(DELETE_FALLBACK)).toBeInTheDocument();
    expect(screen.queryByText(SAVE_FALLBACK)).not.toBeInTheDocument();
  });

  // The other two callers keep the original wording verbatim. Parameterising
  // the fallback must not become a silent copy change for create and edit.
  it('still says the tier could not be SAVED when a create fails unparseably', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: [] }));
    pxqAPI.createTier.mockRejectedValue(unparseable);

    renderPanel();
    await waitFor(() => expect(screen.getByLabelText(/cantidad mínima/i)).toBeInTheDocument());
    await user.type(screen.getByLabelText(/cantidad mínima/i), '5');
    await user.type(screen.getByLabelText(/precio unitario/i), '100');
    await user.click(screen.getByRole('button', { name: /agregar tramo/i }));

    expect(await screen.findByText(SAVE_FALLBACK)).toBeInTheDocument();
  });

  it('still says the tier could not be SAVED when an edit fails unparseably', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.updateTier.mockRejectedValue(unparseable);

    renderPanel();
    await user.click(await screen.findByRole('button', { name: /^editar$/i }));
    await user.click(screen.getByRole('button', { name: /^guardar$/i }));

    expect(await screen.findByText(SAVE_FALLBACK)).toBeInTheDocument();
  });
});

// MercadoLibre hands the wholesale tiers over in ARBITRARY order. Measured in
// production for MLA1563835240, the live read came back as quantities 5, 10, 2
// — and the `ml-webhook` service preserves ML's order on purpose in BOTH
// directions, stating in writing that ordering is the consumer's job. There is
// no guarantee by `quantity` and none by `id` either.
//
// The mirror column had the same defect from the other end: the query behind
// `mirror_tiers` carried no `ORDER BY`, so the database returned rows in
// whatever order it liked. Both columns therefore painted arbitrarily.
//
// A tier is a QUANTITY THRESHOLD ("from 5 units, this price"). Out of sequence
// the column stops being a scale and becomes three unrelated prices that the
// operator has to sort in his head before he can answer the only question the
// panel exists for: does buying more get cheaper.
describe('PxqPanel — tiers are read in quantity order, whatever order they arrive in', () => {
  function mockLive({ mirror_tiers = [], live_tiers = [], live_status = 'ok' } = {}) {
    return {
      data: { item_id: 'MLA001', live_status, live_tiers, mirror_tiers, fetched_at: '2026-08-10T10:00:00Z' },
    };
  }

  // The exact payload MercadoLibre returned in production, order included.
  const mlOrder = () => [
    { id: '3391', quantity: 5, amount: 72990 },
    { id: '3392', quantity: 10, amount: 71000 },
    { id: '3393', quantity: 2, amount: 73990 },
  ];

  const mirrorOutOfOrder = () => [
    { id: 1, cantidad_minima: 10, precio_unitario: 71000, costo_envio_total: 500, ml_price_id: null, estado: 'listo' },
    { id: 2, cantidad_minima: 2, precio_unitario: 73990, costo_envio_total: 500, ml_price_id: null, estado: 'listo' },
    { id: 3, cantidad_minima: 5, precio_unitario: 72990, costo_envio_total: 500, ml_price_id: null, estado: 'listo' },
  ];

  // Scoped to ONE column on purpose. Both columns render "<n> u." spans, and so
  // does the authoring list below them, so a document-wide query would prove
  // nothing about which column is in which order. The anchored regex keeps the
  // match on the span itself rather than on its containing row.
  function quantitiesIn(columnTitle) {
    const column = screen.getByText(columnTitle).parentElement;
    return within(column)
      .getAllByText(/^\d+ u\.$/)
      .map((node) => node.textContent);
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockImplementation(() => true);
  });

  afterEach(() => {
    mockTienePermiso.mockImplementation(() => true);
  });

  it('paints the live column ascending when ML sends 5, 10, 2', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ live_tiers: mlOrder() }));

    renderPanel();

    await screen.findByText('En MercadoLibre (en vivo)');
    // The ORDER of the nodes, not their mere existence: the bug was never a
    // missing row.
    expect(quantitiesIn('En MercadoLibre (en vivo)')).toEqual(['2 u.', '5 u.', '10 u.']);
  });

  it('paints the mirror column ascending by cantidad_minima when the rows arrive unordered', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: mirrorOutOfOrder() }));

    renderPanel();

    await screen.findByText('Mirror local');
    expect(quantitiesIn('Mirror local')).toEqual(['2 u.', '5 u.', '10 u.']);
  });

  // The editing list renders the SAME rows as the mirror column, directly
  // below it. Leaving it unsorted would have it read 10, 2, 5 next to a column
  // reading 2, 5, 10 — the operator would have to map between two orderings of
  // one list to find the row he wants to edit. It does arrive ordered from the
  // backend's `ORDER BY` today, but that is an implicit dependency on another
  // service, not a guarantee this panel holds.
  it('lists the editable tiers ascending too, not just the read column', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: mirrorOutOfOrder() }));

    renderPanel();

    await screen.findByText('Editar tramos');
    expect(quantitiesIn('Editar tramos')).toEqual(['2 u.', '5 u.', '10 u.']);
  });

  // `Array.prototype.sort` sorts IN PLACE. These arrays come straight out of
  // the fetch, are stored in the `useLazyResource` cache, and `mirror_tiers` is
  // handed to `PxqTierAuthoring` and read by the `canImportLive` computation as
  // well. Sorting either one where it lies would reorder it behind every other
  // reader's back, on every render.
  it('never mutates the arrays it was handed', async () => {
    const liveTiers = mlOrder();
    const mirrorTiers = mirrorOutOfOrder();
    pxqAPI.getLive.mockResolvedValue(mockLive({ live_tiers: liveTiers, mirror_tiers: mirrorTiers }));

    renderPanel();

    await screen.findByText('Mirror local');
    expect(quantitiesIn('En MercadoLibre (en vivo)')).toEqual(['2 u.', '5 u.', '10 u.']);
    expect(quantitiesIn('Mirror local')).toEqual(['2 u.', '5 u.', '10 u.']);

    // Asserted on the INPUT objects, which is the only place an in-place sort
    // would show up — the rendered output looks identical either way.
    expect(liveTiers.map((tier) => tier.quantity)).toEqual([5, 10, 2]);
    expect(mirrorTiers.map((tier) => tier.cantidad_minima)).toEqual([10, 2, 5]);
  });
});

// Until now the only way to re-read MercadoLibre was to close the panel and
// open it again: "Reintentar" exists solely inside the error branch, so on the
// happy path — the one where the operator is comparing two columns and wants to
// know whether ML has moved — there was no way to ask again.
describe('PxqPanel — refreshing the live state', () => {
  function mockLive({ mirror_tiers = [], live_tiers = [], live_status = 'ok' } = {}) {
    return {
      data: { item_id: 'MLA001', live_status, live_tiers, mirror_tiers, fetched_at: '2026-08-10T10:00:00Z' },
    };
  }

  const REFRESH_BUTTON = { name: /volver a leer de ml/i };
  const liveTiers = [{ id: 'PXQ1', quantity: 5, amount: 100 }];
  const importedTier = [
    { id: 9, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: null, ml_price_id: 'PXQ1', estado: 'incompleto' },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockImplementation(() => true);
  });

  afterEach(() => {
    mockTienePermiso.mockImplementation(() => true);
  });

  it('offers the refresh on the happy path, not only inside the error branch', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: [], live_tiers: [] }));

    renderPanel();

    await screen.findByText('Mirror local');
    expect(screen.queryByText(/error al cargar precios mayoristas/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', REFRESH_BUTTON));

    await waitFor(() => expect(pxqAPI.getLive).toHaveBeenCalledTimes(2));
  });

  // THE guardrail. `reload()` flips `loading`, so the panel returns its loading
  // branch and unmounts the whole subtree — which is fine for a refresh, since
  // the loading screen IS the feedback. What must not happen is the refresh
  // being wired to `handleAuthoringChanged` "because it also reloads": that
  // function clears both outcomes, and it is allowed to only because AUTHORING
  // invalidates them. Re-reading ML invalidates nothing the operator did.
  it('does NOT clear the import feedback — a refresh is not an authoring mutation', async () => {
    const user = userEvent.setup();
    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [], live_tiers: liveTiers }))
      .mockResolvedValue(mockLive({ mirror_tiers: importedTier, live_tiers: liveTiers }));
    pxqAPI.adoptLive.mockResolvedValue({ data: { item_id: 'MLA001', count: 2, imported: [] } });

    renderPanel();

    await user.click(await screen.findByRole('button', { name: /^importar de mercadolibre$/i }));
    expect(await screen.findByText(/se importaron 2 tramos/i)).toBeInTheDocument();

    await waitFor(() => expect(pxqAPI.getLive).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole('button', REFRESH_BUTTON));
    // Proved to have actually re-read, so the assertion below is not passing
    // on a refresh that never happened.
    await waitFor(() => expect(pxqAPI.getLive).toHaveBeenCalledTimes(3));

    expect(screen.getByText(/se importaron 2 tramos/i)).toBeInTheDocument();
  });
});

// The refresh used to be an icon-only button: the operator could not find it,
// and a control nobody finds is a control that does not exist. It carries its
// own label now, and the panel states how old the reading is next to it — a
// number with no age is indistinguishable from a stale one.
describe('PxqPanel — the refresh names itself and the reading states its age', () => {
  function mockLive({ fetched_at = '2026-08-10T10:00:00Z' } = {}) {
    return {
      data: { item_id: 'MLA001', live_status: 'ok', live_tiers: [], mirror_tiers: [], fetched_at },
    };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the refresh with visible text, not only an aria-label', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive());

    renderPanel();

    const refresh = await screen.findByRole('button', { name: /volver a leer de ml/i });
    expect(refresh).toHaveTextContent(/volver a leer de ml/i);
    expect(refresh.className).toMatch(/outline-subtle-primary/);
    expect(refresh.className).not.toMatch(/icon-only/);
  });

  it('states how old the live reading is, in words, next to the panel title', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-08-10T10:02:30Z'));
    pxqAPI.getLive.mockResolvedValue(mockLive());

    renderPanel();

    expect(await screen.findByText(/hace 2 min/i)).toBeInTheDocument();
  });

  it('says nothing about the age when the response carries no fetched_at', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ fetched_at: null }));

    renderPanel();

    await screen.findByText('Mirror local');
    expect(screen.queryByText(/hace /i)).not.toBeInTheDocument();
    expect(screen.queryByText(/reci\u00e9n/i)).not.toBeInTheDocument();
  });
});

// The age BUCKETS, driven through the panel. The helper is not exported --
// `react-refresh/only-export-components` forbids a non-component export here --
// so the boundaries are asserted where the operator reads them, which is the
// only place they matter anyway.
describe('PxqPanel — every age bucket, at its boundary', () => {
  const NOW = '2026-08-10T12:00:00Z';

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
    vi.spyOn(Date, 'now').mockReturnValue(Date.parse(NOW));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  async function renderAged(fetched_at) {
    pxqAPI.getLive.mockResolvedValue({
      data: { item_id: 'MLA001', live_status: 'ok', live_tiers: [], mirror_tiers: [], fetched_at },
    });
    renderPanel();
    await screen.findByText('Mirror local');
  }

  it.each([
    ['2026-08-10T11:59:31Z', /reci\u00e9n/i],
    ['2026-08-10T11:58:00Z', /hace 2 min/i],
    ['2026-08-10T11:01:00Z', /hace 59 min/i],
    ['2026-08-10T09:00:00Z', /hace 3 h/i],
    ['2026-08-08T12:00:00Z', /hace 2 d/i],
    // Clock skew between the backend and this browser must never print a
    // NEGATIVE age: the reading is fresh, and that is what it says.
    ['2026-08-10T12:05:00Z', /reci\u00e9n/i],
  ])('reads %s as %s', async (fetchedAt, expected) => {
    await renderAged(fetchedAt);
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it('says nothing at all when the timestamp cannot be parsed', async () => {
    await renderAged('not a date');
    expect(screen.queryByText(/le\u00eddo/i)).not.toBeInTheDocument();
  });
});

describe('PxqPanel — primary actions look like buttons', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
  });

  it('renders "Agregar tramo" with the primary variant, not the bare base', async () => {
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

    // The bare `btn-tesla` base is `background: transparent` with a
    // transparent border, so on the panel's grey it reads as text.
    expect(agregar.className).toMatch(/\bprimary\b/);
  });
});

// The panel is READ-ONLY for the time being: prices are read here and changed
// on MercadoLibre itself, through this link. The write path still exists on the
// backend (`pxqAPI.sync`) -- it is only off the UI.
//
// GONE FROM THIS FILE, deliberately, not adapted to keep passing:
//   - 'PxqPanel — price update to ML (PR 4d)'
//   - 'PxqPanel — publish-without-markup override checkbox (slice C2)'
//   - 'PxqPanel — audit_warning renders alongside success ... (D6)'
//   - the price-update halves of the outcome-survival and refresh suites
// They covered the "Actualizar precios en MercadoLibre" button and the loose
// "publicar sin markup" checkbox that hung above it with no context. Both were
// removed from the UI on purpose, so the tests go with them.
describe('PxqPanel — prices are changed on MercadoLibre, through a link', () => {
  function mockLive({ mirror_tiers = [], live_tiers = [] } = {}) {
    return {
      data: { item_id: 'MLA001', live_status: 'ok', live_tiers, mirror_tiers, fetched_at: '2026-08-18T10:00:00Z' },
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

  it('links to this exact publication\u2019s price editor on MercadoLibre, opened safely in a new tab', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));

    renderPanel();

    const link = await screen.findByRole('link', { name: /modificar precios en mercadolibre/i });
    expect(link).toHaveAttribute('href', 'https://vendedores.mercadolibre.com.ar/publicaciones/MLA001/modificar/bomni/precio/');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(link).toHaveAttribute('rel', expect.stringContaining('noreferrer'));
    // An `<a>`, not a `<button>`: it must still LOOK like the panel's primary
    // action, or the operator will not read it as the thing to press.
    expect(link.className).toMatch(/\bprimary\b/);
  });

  // The link leaves the app, and what the operator changes over there is
  // invisible here until the panel re-reads. Saying so is the whole reason the
  // refresh got a name.
  it('tells the operator to re-read when he comes back', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));

    renderPanel();

    expect(await screen.findByText(/volver a leer de ml/i, { selector: 'span, p, div' })).toBeInTheDocument();
  });

  // Navigating to MercadoLibre is not writing from here: `pxq.escribir` gates
  // OUR writes, and there are none behind this link.
  it('offers the link to a pxq.ver-only user, who gets no authoring affordance at all', async () => {
    mockTienePermiso.mockImplementation((code) => code === 'pxq.ver');
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));

    renderPanel();

    expect(await screen.findByRole('link', { name: /modificar precios en mercadolibre/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /agregar tramo/i })).not.toBeInTheDocument();
  });

  it('no longer offers the price-update button or the loose publish-without-markup checkbox', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));

    renderPanel();

    await screen.findByText('Mirror local');
    expect(screen.queryByRole('button', { name: /actualizar precios en mercadolibre/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByText(/publicar precios sin markup/i)).not.toBeInTheDocument();
  });

  it('never calls the sync endpoint from this panel any more', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));

    renderPanel();

    await screen.findByRole('link', { name: /modificar precios en mercadolibre/i });
    expect(pxqAPI.sync).not.toHaveBeenCalled();
  });
});

// Slice A2 of `pxq-markup-antes-de-publicar`: the mirror column shows each
// tier's markup (from `GET /pxq/{item_id}/markup`, slice A1) so the operator
// sees the number BEFORE publishing, instead of only after.
describe('PxqPanel — per-tier markup display (slice A2)', () => {
  function mockLive({ mirror_tiers = [], live_tiers = [], live_status = 'ok' } = {}) {
    return {
      data: { item_id: 'MLA001', live_status, live_tiers, mirror_tiers, fetched_at: '2026-08-18T10:00:00Z' },
    };
  }

  function mockMarkup(tiers) {
    return { data: { item_id: 'MLA001', tiers } };
  }

  const oneTier = () => [
    { id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockImplementation(() => true);
  });

  afterEach(() => {
    mockTienePermiso.mockImplementation(() => true);
  });

  it('renders the resolved markup percentage next to its mirror tier', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier() }));
    pxqAPI.getMarkup.mockResolvedValue(mockMarkup([{ tier_id: 1, markup: 0.25, limpio: 500, comision_total: 75 }]));

    renderPanel();

    await screen.findByText('Mirror local');
    expect(pxqAPI.getMarkup).toHaveBeenCalledWith('MLA001');
    await screen.findByText(/25[.,]0%/);
  });

  it('renders a human reason instead of a number when the markup could not be computed', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier() }));
    pxqAPI.getMarkup.mockResolvedValue(mockMarkup([{ tier_id: 1, reason: 'shipping_unavailable' }]));

    renderPanel();

    await screen.findByText('Mirror local');
    expect(await screen.findByText(/falta el costo de env[ií]o/i)).toBeInTheDocument();
    // Never a fabricated number for an unresolved tier.
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  });

  it('renders a different reason for missing product pricing data', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier() }));
    pxqAPI.getMarkup.mockResolvedValue(mockMarkup([{ tier_id: 1, reason: 'product_data_missing' }]));

    renderPanel();

    await screen.findByText('Mirror local');
    expect(await screen.findByText(/datos del producto/i)).toBeInTheDocument();
  });

  it('shows a neutral placeholder while the markup fetch is still in flight', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier() }));
    let resolveMarkup;
    pxqAPI.getMarkup.mockReturnValue(
      new Promise((resolve) => {
        resolveMarkup = resolve;
      }),
    );

    renderPanel();

    await screen.findByText('Mirror local');
    expect(screen.getByText(/calculando/i)).toBeInTheDocument();

    resolveMarkup(mockMarkup([{ tier_id: 1, markup: 0.1 }]));
    await screen.findByText(/10[.,]0%/);
  });

  it('never calls the markup endpoint for a pxq.ver-only user (canRead gate holds for markup too)', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier() }));
    pxqAPI.getMarkup.mockResolvedValue(mockMarkup([{ tier_id: 1, markup: 0.25 }]));

    renderPanel();
    await screen.findByText('Mirror local');
    expect(pxqAPI.getMarkup).toHaveBeenCalledTimes(1);
  });

  it('does not fabricate a markup for a tier the batch response never mentions', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier() }));
    pxqAPI.getMarkup.mockResolvedValue(mockMarkup([]));

    renderPanel();

    await screen.findByText('Mirror local');
    expect(screen.queryByText(/calculando/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  });
});

// Follow-up to slice A2: `handleAuthoringChanged` reloaded the MIRROR
// (`reload()`) but never the MARKUP resource, so `usePxqMarkup`'s cache kept
// serving the pre-edit percentage after a tier's price/shipping changed --
// exactly the stale/fabricated number the spec forbids. See design D2,
// "Recompute on relevant data change".
// The markup is the number the operator opened this panel for, and it used to
// render as loose plain text among the other cells. This suite pins the
// STRUCTURE -- the percentage is its own element, separable from the label
// around it, which is what lets the stylesheet give it any emphasis at all.
describe('PxqPanel — the markup cell has a visual hierarchy', () => {
  function mockLive({ mirror_tiers = [] } = {}) {
    return {
      data: { item_id: 'MLA001', live_status: 'ok', live_tiers: [], mirror_tiers, fetched_at: '2026-08-18T10:00:00Z' },
    };
  }
  const oneTier = [{ id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' }];
  const mockMarkup = (tiers) => ({ data: { item_id: 'MLA001', tiers } });

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
  });

  it('gives the resolved percentage its own class, distinct from the label around it', async () => {
    pxqAPI.getLive.mockResolvedValue(mockLive({ mirror_tiers: oneTier }));
    pxqAPI.getMarkup.mockResolvedValue(mockMarkup([{ tier_id: 1, markup: 0.184 }]));

    renderPanel();

    const percent = await screen.findByText(/18[.,]4%/);
    expect(percent.className).toMatch(/pxqMarkupValue/);
  });

  // The COLOURS of these three states are asserted in
  // `src/test/visual/pxqPanel.visual.test.jsx`, not here: the unit project runs
  // with `css: false`, so `styles.whatever` is a proxy that echoes back any key
  // it is asked for. A class the CSS module never defined looks identical to a
  // defined one in this project -- which is precisely how
  // `.pxqMarkupPending`/`.pxqMarkupUnavailable` shipped referenced-but-missing.
});

describe('PxqPanel — markup recompute on authoring change (design D2)', () => {
  function mockLive({ mirror_tiers = [], live_tiers = [], live_status = 'ok' } = {}) {
    return {
      data: { item_id: 'MLA001', live_status, live_tiers, mirror_tiers, fetched_at: '2026-08-18T10:00:00Z' },
    };
  }

  function mockMarkup(tiers) {
    return { data: { item_id: 'MLA001', tiers } };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockImplementation(() => true);
  });

  afterEach(() => {
    mockTienePermiso.mockImplementation(() => true);
  });

  it('refetches markup after editing a tier and shows the recomputed value', async () => {
    const user = userEvent.setup();
    const tierBefore = { id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' };
    const tierAfter = { ...tierBefore, precio_unitario: 150 };

    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [tierBefore] }))
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [tierAfter] }));
    pxqAPI.getMarkup
      .mockResolvedValueOnce(mockMarkup([{ tier_id: 1, markup: 0.1 }]))
      .mockResolvedValueOnce(mockMarkup([{ tier_id: 1, markup: 0.4 }]));
    pxqAPI.updateTier.mockResolvedValue({ data: tierAfter });

    renderPanel();

    await screen.findByText(/10[.,]0%/);

    await user.click(screen.getByRole('button', { name: /^editar$/i }));
    const precioInput = screen.getByLabelText(/precio unitario/i);
    await user.clear(precioInput);
    await user.type(precioInput, '150');
    await user.click(screen.getByRole('button', { name: /guardar/i }));

    await waitFor(() => expect(pxqAPI.getMarkup).toHaveBeenCalledTimes(2));
    await screen.findByText(/40[.,]0%/);
    expect(screen.queryByText(/10[.,]0%/)).not.toBeInTheDocument();
  });

  it('keeps an already-rendered tier markup on screen while the post-authoring refetch is in flight, without an intervening "Calculando" placeholder', async () => {
    const user = userEvent.setup();
    const tierA = { id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' };
    const tierB = { id: 2, cantidad_minima: 10, precio_unitario: 200, costo_envio_total: 40, ml_price_id: null, estado: 'listo' };
    const tierBAfter = { ...tierB, precio_unitario: 250 };

    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [tierA, tierB] }))
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [tierA, tierBAfter] }));
    pxqAPI.getMarkup.mockResolvedValueOnce(
      mockMarkup([
        { tier_id: 1, markup: 0.2 },
        { tier_id: 2, markup: 0.3 },
      ]),
    );
    let resolveSecondMarkup;
    pxqAPI.getMarkup.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveSecondMarkup = resolve;
      }),
    );
    pxqAPI.updateTier.mockResolvedValue({ data: tierBAfter });

    renderPanel();

    await screen.findByText(/20[.,]0%/);
    await screen.findByText(/30[.,]0%/);

    const editButtons = screen.getAllByRole('button', { name: /^editar$/i });
    await user.click(editButtons[1]);
    const precioInput = screen.getByLabelText(/precio unitario/i);
    await user.clear(precioInput);
    await user.type(precioInput, '250');
    await user.click(screen.getByRole('button', { name: /guardar/i }));

    await waitFor(() => expect(pxqAPI.getMarkup).toHaveBeenCalledTimes(2));

    // Tier A's already-known markup stays visible -- no placeholder pushed it out.
    expect(screen.getByText(/20[.,]0%/)).toBeInTheDocument();
    expect(screen.queryByText(/calculando/i)).not.toBeInTheDocument();

    resolveSecondMarkup(mockMarkup([{ tier_id: 1, markup: 0.2 }, { tier_id: 2, markup: 0.5 }]));
    await screen.findByText(/50[.,]0%/);
  });

  it('refetches markup after importing tiers from ML so the new rows get their reason, not a blank cell', async () => {
    const user = userEvent.setup();

    pxqAPI.getLive
      .mockResolvedValueOnce(mockLive({ mirror_tiers: [], live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 100 }] }))
      .mockResolvedValueOnce(
        mockLive({
          mirror_tiers: [{ id: 9, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: null, ml_price_id: 'PXQ1', estado: 'incompleto' }],
          live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 100 }],
        }),
      );
    // First markup batch runs against the empty mirror; the post-import one is
    // the first that can mention the adopted row.
    pxqAPI.getMarkup
      .mockResolvedValueOnce(mockMarkup([]))
      .mockResolvedValueOnce(mockMarkup([{ tier_id: 9, reason: 'shipping_unavailable' }]));
    pxqAPI.adoptLive.mockResolvedValue({ data: { item_id: 'MLA001', count: 1, imported: [] } });

    renderPanel();
    await user.click(await screen.findByRole('button', { name: /^importar de mercadolibre$/i }));

    await waitFor(() => expect(pxqAPI.getMarkup).toHaveBeenCalledTimes(2));
    await screen.findByText(/^falta el costo de envío del bulto$/i);
  });
});
